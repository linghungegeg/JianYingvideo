import argparse
import json
import sys
import time
from pathlib import Path

import frida


SCRIPT_SOURCE = r"""
function safeReadUtf16(ptrValue) {
  if (ptrValue.isNull()) return "";
  try {
    return ptrValue.readUtf16String() || "";
  } catch (err) {
    return "<readUtf16String failed>";
  }
}

function safeReadAnsi(ptrValue) {
  if (ptrValue.isNull()) return "";
  try {
    return ptrValue.readAnsiString() || "";
  } catch (err) {
    return "<readAnsiString failed>";
  }
}

function sendEvent(type, payload) {
  send({ type, payload });
}

function findExport(moduleName, exportName) {
  try {
    if (typeof Module.findExportByName === "function") {
      return Module.findExportByName(moduleName, exportName);
    }
  } catch (err) {}
  try {
    if (typeof Module.getExportByName === "function") {
      return Module.getExportByName(moduleName, exportName);
    }
  } catch (err) {}
  try {
    const moduleObj = Process.getModuleByName(moduleName);
    if (moduleObj && typeof moduleObj.findExportByName === "function") {
      return moduleObj.findExportByName(exportName);
    }
    if (moduleObj && typeof moduleObj.getExportByName === "function") {
      return moduleObj.getExportByName(exportName);
    }
  } catch (err) {}
  return null;
}

function hookExport(moduleName, exportName, callbacks) {
  const addr = findExport(moduleName, exportName);
  if (!addr) {
    sendEvent("missing_export", { moduleName, exportName });
    return;
  }
  Interceptor.attach(addr, callbacks);
  sendEvent("hooked", { moduleName, exportName, address: addr.toString() });
}

hookExport("kernel32.dll", "CreateFileW", {
  onEnter(args) {
    this.path = safeReadUtf16(args[0]);
    this.access = args[1].toUInt32();
    this.disposition = args[4].toUInt32();
  },
  onLeave(retval) {
    sendEvent("CreateFileW", {
      path: this.path,
      access: this.access,
      disposition: this.disposition,
      handle: retval.toString()
    });
  }
});

hookExport("kernel32.dll", "WriteFile", {
  onEnter(args) {
    this.handle = args[0].toString();
    this.size = args[2].toUInt32();
  },
  onLeave(retval) {
    sendEvent("WriteFile", {
      handle: this.handle,
      size: this.size,
      ok: !retval.isNull()
    });
  }
});

hookExport("kernel32.dll", "GetEnvironmentVariableW", {
  onEnter(args) {
    this.name = safeReadUtf16(args[0]);
  },
  onLeave(retval) {
    sendEvent("GetEnvironmentVariableW", {
      name: this.name,
      result: retval.toInt32()
    });
  }
});

hookExport("kernel32.dll", "GetCommandLineW", {
  onLeave(retval) {
    sendEvent("GetCommandLineW", {
      value: safeReadUtf16(retval)
    });
  }
});

hookExport("kernel32.dll", "GetModuleFileNameW", {
  onEnter(args) {
    this.hModule = args[0].toString();
    this.buffer = args[1];
    this.size = args[2].toUInt32();
  },
  onLeave(retval) {
    sendEvent("GetModuleFileNameW", {
      hModule: this.hModule,
      size: this.size,
      result: retval.toInt32(),
      value: safeReadUtf16(this.buffer)
    });
  }
});

hookExport("kernel32.dll", "OpenProcess", {
  onEnter(args) {
    this.access = args[0].toUInt32();
    this.pid = args[2].toUInt32();
  },
  onLeave(retval) {
    sendEvent("OpenProcess", {
      access: this.access,
      pid: this.pid,
      handle: retval.toString()
    });
  }
});

hookExport("kernel32.dll", "CreateProcessW", {
  onEnter(args) {
    this.applicationName = safeReadUtf16(args[0]);
    this.commandLine = safeReadUtf16(args[1]);
  },
  onLeave(retval) {
    sendEvent("CreateProcessW", {
      applicationName: this.applicationName,
      commandLine: this.commandLine,
      ok: retval.toInt32()
    });
  }
});

hookExport("kernel32.dll", "CreateProcessA", {
  onEnter(args) {
    this.applicationName = safeReadAnsi(args[0]);
    this.commandLine = safeReadAnsi(args[1]);
  },
  onLeave(retval) {
    sendEvent("CreateProcessA", {
      applicationName: this.applicationName,
      commandLine: this.commandLine,
      ok: retval.toInt32()
    });
  }
});

hookExport("shell32.dll", "ShellExecuteExW", {
  onEnter(args) {
    this.execInfo = args[0];
  },
  onLeave(retval) {
    sendEvent("ShellExecuteExW", {
      execInfo: this.execInfo.toString(),
      ok: retval.toInt32()
    });
  }
});

hookExport("kernel32.dll", "WaitForSingleObject", {
  onEnter(args) {
    this.handle = args[0].toString();
    this.timeout = args[1].toUInt32();
  },
  onLeave(retval) {
    sendEvent("WaitForSingleObject", {
      handle: this.handle,
      timeout: this.timeout,
      result: retval.toUInt32()
    });
  }
});

hookExport("kernel32.dll", "IsDebuggerPresent", {
  onLeave(retval) {
    sendEvent("IsDebuggerPresent", {
      result: retval.toInt32()
    });
  }
});

hookExport("kernel32.dll", "CheckRemoteDebuggerPresent", {
  onEnter(args) {
    this.handle = args[0].toString();
  },
  onLeave(retval) {
    sendEvent("CheckRemoteDebuggerPresent", {
      handle: this.handle,
      ok: retval.toInt32()
    });
  }
});

hookExport("kernel32.dll", "ExitProcess", {
  onEnter(args) {
    sendEvent("ExitProcess", {
      code: args[0].toUInt32()
    });
  }
});

hookExport("ntdll.dll", "NtQueryInformationProcess", {
  onEnter(args) {
    this.processHandle = args[0].toString();
    this.infoClass = args[1].toUInt32();
  },
  onLeave(retval) {
    sendEvent("NtQueryInformationProcess", {
      processHandle: this.processHandle,
      infoClass: this.infoClass,
      status: retval.toInt32()
    });
  }
});
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Frida trace cppreader.exe API usage")
    parser.add_argument("--out", default="", help="write JSONL trace to this file")
    parser.add_argument("argv", nargs="+", help="target argv, starting with cppreader.exe")
    args = parser.parse_args()

    out_path = Path(args.out).resolve() if args.out else None
    handle = out_path.open("w", encoding="utf-8") if out_path else None
    events = []

    def emit(record: dict) -> None:
        line = json.dumps(record, ensure_ascii=False)
        print(line)
        if handle:
            handle.write(line + "\n")
            handle.flush()
        events.append(record)

    device = frida.get_local_device()
    pid = device.spawn(args.argv)
    session = device.attach(pid)
    script = session.create_script(SCRIPT_SOURCE)

    def on_message(message, data):
        emit({"ts": time.time(), "message": message})

    script.on("message", on_message)
    script.load()
    device.resume(pid)

    def process_alive(target_pid: int) -> bool:
        try:
            return any(proc.pid == target_pid for proc in device.enumerate_processes())
        except frida.ProcessNotFoundError:
            return False

    while True:
        if not process_alive(pid):
            break
        time.sleep(0.05)

    session.detach()
    if handle:
        handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
