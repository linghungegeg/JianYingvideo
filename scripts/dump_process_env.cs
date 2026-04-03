using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;

internal static class Program
{
    private const uint PROCESS_QUERY_INFORMATION = 0x0400;
    private const uint PROCESS_VM_READ = 0x0010;

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_BASIC_INFORMATION
    {
        public IntPtr Reserved1;
        public IntPtr PebBaseAddress;
        public IntPtr Reserved2_0;
        public IntPtr Reserved2_1;
        public IntPtr UniqueProcessId;
        public IntPtr InheritedFromUniqueProcessId;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct UNICODE_STRING
    {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RTL_USER_PROCESS_PARAMETERS
    {
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 16)]
        public byte[] Reserved1;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 10)]
        public IntPtr[] Reserved2;
        public UNICODE_STRING ImagePathName;
        public UNICODE_STRING CommandLine;
        public IntPtr Environment;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadProcessMemory(
        IntPtr hProcess,
        IntPtr lpBaseAddress,
        [Out] byte[] lpBuffer,
        int dwSize,
        out IntPtr lpNumberOfBytesRead);

    [DllImport("ntdll.dll")]
    private static extern int NtQueryInformationProcess(
        IntPtr processHandle,
        int processInformationClass,
        ref PROCESS_BASIC_INFORMATION processInformation,
        int processInformationLength,
        out int returnLength);

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length < 1)
            {
                Console.Error.WriteLine("usage: <pid>");
                return 2;
            }

            uint pid;
            if (!uint.TryParse(args[0], out pid))
            {
                Console.Error.WriteLine("invalid pid");
                return 2;
            }

            var handle = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, false, pid);
            if (handle == IntPtr.Zero)
            {
                throw new Win32Exception(Marshal.GetLastWin32Error(), "OpenProcess failed");
            }

            try
            {
                var pbi = new PROCESS_BASIC_INFORMATION();
                int returnLength;
                var nt = NtQueryInformationProcess(handle, 0, ref pbi, Marshal.SizeOf(typeof(PROCESS_BASIC_INFORMATION)), out returnLength);
                if (nt != 0)
                {
                    throw new Exception("NtQueryInformationProcess failed: " + nt);
                }

                IntPtr pebAddress = pbi.PebBaseAddress;
                IntPtr processParametersPtr = ReadIntPtr(handle, pebAddress + 0x20);
                var rupp = ReadStruct<RTL_USER_PROCESS_PARAMETERS>(handle, processParametersPtr);

                string imagePath = ReadUnicodeString(handle, rupp.ImagePathName);
                string commandLine = ReadUnicodeString(handle, rupp.CommandLine);
                string[] envPairs = ReadEnvironmentBlock(handle, rupp.Environment, 131072);

                Console.OutputEncoding = Encoding.UTF8;
                Console.WriteLine("{");
                Console.WriteLine("  \"imagePath\": " + Json(imagePath) + ",");
                Console.WriteLine("  \"commandLine\": " + Json(commandLine) + ",");
                Console.WriteLine("  \"environment\": {");
                bool first = true;
                foreach (var kv in ParseEnvPairs(envPairs))
                {
                    if (!first) Console.WriteLine(",");
                    Console.Write("    " + Json(kv.Key) + ": " + Json(kv.Value));
                    first = false;
                }
                Console.WriteLine();
                Console.WriteLine("  }");
                Console.WriteLine("}");
                return 0;
            }
            finally
            {
                CloseHandle(handle);
            }
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine(ex.GetType().FullName + ": " + ex.Message);
            return 10;
        }
    }

    private static Dictionary<string, string> ParseEnvPairs(string[] pairs)
    {
        var map = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var pair in pairs)
        {
            if (string.IsNullOrEmpty(pair)) continue;
            int idx = pair.IndexOf('=');
            if (idx <= 0) continue;
            var key = pair.Substring(0, idx);
            var value = pair.Substring(idx + 1);
            map[key] = value;
        }
        return map;
    }

    private static string[] ReadEnvironmentBlock(IntPtr process, IntPtr envPtr, int maxBytes)
    {
        var buffer = new byte[maxBytes];
        IntPtr read;
        if (!ReadProcessMemory(process, envPtr, buffer, buffer.Length, out read))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "ReadProcessMemory(environment) failed");
        }
        int limit = (int)read;
        int end = 0;
        for (int i = 0; i + 3 < limit; i += 2)
        {
            if (buffer[i] == 0 && buffer[i + 1] == 0 && buffer[i + 2] == 0 && buffer[i + 3] == 0)
            {
                end = i;
                break;
            }
        }
        if (end == 0) end = limit;
        string block = Encoding.Unicode.GetString(buffer, 0, end);
        return block.Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries);
    }

    private static string ReadUnicodeString(IntPtr process, UNICODE_STRING us)
    {
        if (us.Buffer == IntPtr.Zero || us.Length == 0) return "";
        var buffer = new byte[us.Length];
        IntPtr read;
        if (!ReadProcessMemory(process, us.Buffer, buffer, buffer.Length, out read))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "ReadProcessMemory(string) failed");
        }
        return Encoding.Unicode.GetString(buffer, 0, (int)read);
    }

    private static T ReadStruct<T>(IntPtr process, IntPtr address) where T : struct
    {
        int size = Marshal.SizeOf(typeof(T));
        var buffer = new byte[size];
        IntPtr read;
        if (!ReadProcessMemory(process, address, buffer, size, out read))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "ReadProcessMemory(struct) failed");
        }
        var handle = GCHandle.Alloc(buffer, GCHandleType.Pinned);
        try
        {
            return (T)Marshal.PtrToStructure(handle.AddrOfPinnedObject(), typeof(T));
        }
        finally
        {
            handle.Free();
        }
    }

    private static IntPtr ReadIntPtr(IntPtr process, IntPtr address)
    {
        var buffer = new byte[IntPtr.Size];
        IntPtr read;
        if (!ReadProcessMemory(process, address, buffer, buffer.Length, out read))
        {
            throw new Win32Exception(Marshal.GetLastWin32Error(), "ReadProcessMemory(pointer) failed");
        }
        return IntPtr.Size == 8
            ? new IntPtr(BitConverter.ToInt64(buffer, 0))
            : new IntPtr(BitConverter.ToInt32(buffer, 0));
    }

    private static string Json(string text)
    {
        if (text == null) return "null";
        return "\"" + text.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n") + "\"";
    }
}
