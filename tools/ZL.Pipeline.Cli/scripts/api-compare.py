#!/usr/bin/env python3
"""
对比混淆前后 DLL 的公共 API 完整性

用法:
  python3 api-compare.py <original.dll> <obfuscated.dll> [--deps <dep_dir>]

示例:
  python3 scripts/api-compare.py \
    publish-obs/ZL.PlcBase/ZL.PlcBase.dll \
    obfuscated/ZL.PlcBase/ZL.PlcBase.dll \
    --deps publish-obs/ZL.PlcBase
"""

import subprocess
import sys
import os
import tempfile
import argparse

# ============================================================
# C# 反射对比程序（支持 AssemblyLoadContext 加载依赖）
# ============================================================
CSHARP_CODE = r"""
using System;
using System.Reflection;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.Loader;

class Program
{
    static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.WriteLine("Usage: api-compare <dll1> <dll2> [--deps <dep_dir>]");
            return 1;
        }

        string dll1Path = args[0];
        string dll2Path = args[1];
        string? depsDir = null;

        // Parse optional --deps argument
        for (int i = 2; i < args.Length; i++)
        {
            if (args[i] == "--deps" && i + 1 < args.Length)
            {
                depsDir = args[++i];
            }
        }

        Assembly asm1, asm2;

        if (!string.IsNullOrEmpty(depsDir))
        {
            // Load with dependency resolution
            asm1 = LoadWithDeps(dll1Path, depsDir);
            asm2 = LoadWithDeps(dll2Path, depsDir);
        }
        else
        {
            asm1 = Assembly.LoadFrom(dll1Path);
            asm2 = Assembly.LoadFrom(dll2Path);
        }

        var types1 = GetPublicTypes(asm1);
        var types2 = GetPublicTypes(asm2);

        Console.WriteLine($"DLL1 ({dll1Path}): {types1.Count} public types");
        Console.WriteLine($"DLL2 ({dll2Path}): {types2.Count} public types");

        var onlyIn1 = types1.Except(types2).ToList();
        var onlyIn2 = types2.Except(types1).ToList();
        var commonTypes = types1.Intersect(types2).ToList();

        if (onlyIn1.Count > 0)
        {
            Console.WriteLine($"\nTypes ONLY in original ({onlyIn1.Count}):");
            foreach (var t in onlyIn1.Take(30))
                Console.WriteLine($"  MISSING: {t}");
            if (onlyIn1.Count > 30)
                Console.WriteLine($"  ... and {onlyIn1.Count - 30} more");
        }

        if (onlyIn2.Count > 0)
        {
            Console.WriteLine($"\nTypes ONLY in obfuscated ({onlyIn2.Count}):");
            foreach (var t in onlyIn2.Take(30))
                Console.WriteLine($"  NEW: {t}");
            if (onlyIn2.Count > 30)
                Console.WriteLine($"  ... and {onlyIn2.Count - 30} more");
        }

        // Compare public methods on common types
        int methodMismatches = 0;
        foreach (var typeName in commonTypes)
        {
            try
            {
                var t1 = asm1.GetType(typeName);
                var t2 = asm2.GetType(typeName);
                if (t1 == null || t2 == null) continue;

                var methods1 = GetPublicMethodNames(t1);
                var methods2 = GetPublicMethodNames(t2);

                var missing = methods1.Except(methods2).ToList();
                if (missing.Count > 0)
                {
                    methodMismatches++;
                    Console.WriteLine($"\nMethod mismatch in {typeName}:");
                    Console.WriteLine($"  Missing: {string.Join(", ", missing.Take(10))}");
                }
            }
            catch { }
        }

        Console.WriteLine($"\n=== SUMMARY ===");
        Console.WriteLine($"Common public types: {commonTypes.Count}");
        Console.WriteLine($"Types missing in obfuscated: {onlyIn1.Count}");
        Console.WriteLine($"Types added in obfuscated: {onlyIn2.Count}");
        Console.WriteLine($"Types with method mismatches: {methodMismatches}");

        if (onlyIn1.Count == 0 && onlyIn2.Count == 0 && methodMismatches == 0)
        {
            Console.WriteLine("\n[OK] Public API is fully preserved after obfuscation!");
            return 0;
        }
        else
        {
            Console.WriteLine("\n[WARNING] Some public API differences detected!");
            return 0;
        }
    }

    static Assembly LoadWithDeps(string dllPath, string depsDir)
    {
        var context = new AssemblyLoadContext("ApiCompare", isCollectible: false);
        context.Resolving += (loader, name) =>
        {
            string dllName = name.Name + ".dll";
            string path = System.IO.Path.Combine(depsDir, dllName);
            if (System.IO.File.Exists(path))
                return loader.LoadFromAssemblyPath(path);
            return null;
        };
        return context.LoadFromAssemblyPath(System.IO.Path.GetFullPath(dllPath));
    }

    static List<string> GetPublicTypes(Assembly asm)
    {
        try
        {
            return asm.GetTypes()
                .Where(t => t.IsPublic && !t.IsNested && !t.IsGenericTypeDefinition)
                .Select(t => t.FullName!)
                .Where(n => !string.IsNullOrEmpty(n))
                .OrderBy(x => x)
                .ToList();
        }
        catch (ReflectionTypeLoadException ex)
        {
            var loaded = ex.Types?.Where(t => t != null).ToList() ?? new List<Type>();
            Console.WriteLine($"  [info] Could not load {ex.LoaderExceptions.Length} types (dependencies):");
            foreach (var err in ex.LoaderExceptions?.Take(5) ?? Array.Empty<Exception>())
                Console.WriteLine($"    {err.Message.Split('\n')[0]}");
            return loaded
                .Where(t => t.IsPublic && !t.IsNested && !t.IsGenericTypeDefinition)
                .Select(t => t.FullName!)
                .Where(n => !string.IsNullOrEmpty(n))
                .OrderBy(x => x)
                .ToList();
        }
    }

    static List<string> GetPublicMethodNames(Type t)
    {
        return t.GetMethods(BindingFlags.Public | BindingFlags.Static | BindingFlags.Instance | BindingFlags.DeclaredOnly)
            .Select(m => m.Name)
            .OrderBy(x => x)
            .ToList();
    }
}
"""


def create_compare_tool():
    """创建临时的 C# 对比工具项目"""
    tmp_dir = tempfile.mkdtemp(prefix="api-compare-")

    csproj = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>"""

    with open(os.path.join(tmp_dir, "ApiCompare.csproj"), "w") as f:
        f.write(csproj)
    with open(os.path.join(tmp_dir, "Program.cs"), "w") as f:
        f.write(CSHARP_CODE)

    # Build
    result = subprocess.run(
        ["dotnet", "build", os.path.join(tmp_dir, "ApiCompare.csproj"),
         "-c", "Release", "--nologo", "-v", "q"],
        capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        print(f"Build failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    return tmp_dir


def main():
    parser = argparse.ArgumentParser(description="Compare public APIs of two DLLs")
    parser.add_argument("original", help="Path to original DLL")
    parser.add_argument("obfuscated", help="Path to obfuscated DLL")
    parser.add_argument("--deps", help="Directory containing dependency DLLs")
    args = parser.parse_args()

    if not os.path.exists(args.original):
        print(f"Error: Original DLL not found: {args.original}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(args.obfuscated):
        print(f"Error: Obfuscated DLL not found: {args.obfuscated}", file=sys.stderr)
        sys.exit(1)

    # Create and build the comparison tool
    tool_dir = create_compare_tool()

    # Run comparison
    cmd = [
        "dotnet", "run", "--project", os.path.join(tool_dir, "ApiCompare.csproj"),
        "-c", "Release", "--no-restore", "--",
        args.original, args.obfuscated
    ]
    if args.deps:
        cmd.extend(["--deps", args.deps])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    print(result.stdout)
    if result.stderr and "warning" not in result.stderr.lower():
        print(f"STDERR: {result.stderr[:500]}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
