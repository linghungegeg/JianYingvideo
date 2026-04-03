using System;
using System.Diagnostics;
using System.Linq;

internal static class Program
{
    private static int Main(string[] args)
    {
        if (args.Length < 1)
        {
            Console.Error.WriteLine("usage: <cppreader-path> [args...]");
            return 2;
        }

        var start = new ProcessStartInfo
        {
            FileName = args[0],
            UseShellExecute = false,
            CreateNoWindow = true,
            Arguments = string.Join(" ", args.Skip(1).Select(QuoteArg)),
        };

        var proc = Process.Start(start);
        if (proc == null)
        {
            Console.Error.WriteLine("failed to launch child");
            return 3;
        }

        using (proc)
        {
            proc.WaitForExit();
            return proc.ExitCode;
        }
    }

    private static string QuoteArg(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "\"\"";
        }

        if (value.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
        {
            return value;
        }

        return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }
}
