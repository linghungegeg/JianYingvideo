# Official Reader Runtime Notes (2026-04-03)

## Scope

Evidence captured from:

- `E:\JianYingApi\VideoFactory\runtime_tools\official_reader`
- `E:\JianYingApi\VideoFactory\build\obfuscated\runtime_tools\official_reader`
- `D:\gg-jy-assistant`

Goal:

- map the real official draft read/write chain
- identify which parts are already reproduced locally
- identify the remaining GG/runtime-coupled constraints

## Confirmed Runtime Shape

`official_reader` is not a single executable. The effective runtime is:

- Electron JS bundle
- `build/electron/utils/p.js`
- `build/electron/utils/runCommand.js`
- `resources/enhance/win32/x64/cppreader.exe`
- `electron-store` config/state
- `userData` directory passed into Electron

The bundled and 2026-03-30 obfuscated `cppreader.exe` are byte-identical.

- SHA256: `d1ee4a1cc2cd3c84680b21632a808287acb6691ae60cfdab26995560a49f3d3a`

## Reader Call Chain

The official read path in `p.js` is:

1. `handleGetActivationStatus()`
2. validate `k6`
3. validate `g6`
4. validate freshness of `g6[0:10]`
5. validate `g6[16]` and `g6[17]` against local RAM parity
6. if `infoPath` already starts with `{`, skip private reader and only polyfill defaults
7. otherwise call `rc(...)`
8. `rc(...)` spawns `cppreader.exe`
9. expect `<infoPath>.rec`
10. decrypt `.rec` using `aes-128-ecb` with `md5(k6)`
11. JSON parse
12. apply polyfill defaults derived from `k6`

Observed `cppreader.exe` argv shape:

1. `cppreader.exe`
2. `k6`
3. `apiParam`
4. `infoPath`
5. `g6.substring(10)`
6. `softwareKeyName`
7. `utilsPath`
8. `userDataPath`

## State Constraints

Visible state consumed by `p.js`:

- `k6`
- `k6p`
- `g6`
- `lits`
- `litscfc`
- `oa`
- `d`

Current observed configs do not contain `p` or `a` activation fields.

Observed config shape on both bundled and roaming installs:

- `k6 = 0341912770001007`
- `k6p = MTI1NDgwNDM4ODYyNDUxMDMwMDQ=`
- `g6 = <26 digits>`
- `p = null`
- `a = null`

This matters because `p.js` computes:

- `apiParam = getApiParamK()`
- if `apiParam.length === 20`, it replaces that with `base64decode(k6p)`
- otherwise it uses `apiParam` directly

Given current configs have no `p/a`, the effective path on this machine is the `k6p` path, not an activation-code pair path.

## Hard Constraints Confirmed

The current reader path is not a pure static parser. It has hard runtime checks:

- `k6` must exist and contain `000100` at positions `9:15`
- `g6` must be 26 digits
- `g6[0:10]` must be close to current unix time
- current unix time must be >= `1743996194`
- `g6[16]` and `g6[17]` must match parity digits derived from `os.totalmem()`
- `handleGetActivationStatus()` must not report `expired`

The GG app main process also refreshes runtime state from the network:

- fetches notice / command / `k6` / `k6p` / `g6`
- updates `LATEST_INTERNET_TIMESTAMP_S`
- persists these values back into `electron-store`

So yes: there is a real external-hard-constraint risk. A protocol/state change on their side can invalidate the current compatibility path.

## Writer Chain

The writer exposed by `p.js` is much simpler than the reader.

`p.js` export `_____`:

- writes plain payload text to `infoPath`
- synthesizes a sibling timeline-root dirname from `k6`
- if that root exists, mirrors the same payload into `project.json.main_timeline_id/<basename(infoPath)>`

This is not an encrypted writer. It is a plain write + mirror helper.

Conclusion:

- the difficult part is the private read/decrypt path
- the `p.js` writer alone is not the missing magic for stable official drafts

## Dynamic Tests Run

### Direct `cppreader.exe`

Tested with:

- bundled runtime
- external `D:\gg-jy-assistant`
- original official draft path
- ASCII shadow copy of the same draft

Result:

- return code `0`
- no stdout
- no stderr
- no `.rec` emitted

### Node bridge calling `p.js`

Tested through the local bridge in `official_draft_replace_service.py`.

Result on both bundled and external runtime:

- `{"status":"error","data":"读取草稿出现错误。"}`

This means:

- argv order is no longer the main uncertainty
- either `cppreader` depends on more runtime state than currently supplied
- or `p.js` still assumes additional Electron/app bootstrapping not covered by the current stub
- or the target `draft_content.json` no longer matches the expected encrypted input contract

## Runtime Capture Breakthrough

Using the real GG Electron app through renderer IPC:

- launch `谷哥剪映助手.exe` with `--remote-debugging-port=9222`
- temporarily set roaming `config.json` field `t` to a non-zero value so `preReplaceMaterial` can execute
- call `window.electronAPI.preReplaceMaterial({ infoPath, replaceTypes })`

Observed result:

- the business call no longer fails at `p()` / reader stage
- a short-lived `draft_content.json.rec` file is created beside the source draft
- the file exists for roughly `60ms` before `et()` deletes it

This proves:

- the real app context can successfully drive `cppreader`
- the failure in local bridge/direct subprocess mode is environmental, not just bad argv

## `.rec` File Format

Captured artifact:

- [4y3_1_runtime_capture.rec](/E:/JianYingApi/VideoFactory/build/reverse_capture/4y3_1_runtime_capture.rec)

Key facts:

- `.rec` is UTF-8 text containing hex characters
- it is not raw ciphertext bytes
- `p.js et()` decrypt rule is correct:
  - decode hex text to bytes
  - AES-128-ECB
  - key = `md5(k6)`
  - plaintext is UTF-8 JSON

Captured decrypt output:

- [4y3_1_runtime_capture.decrypted_utf8.json](/E:/JianYingApi/VideoFactory/build/reverse_capture/4y3_1_runtime_capture.decrypted_utf8.json)

Companion helper script:

- [decrypt_runtime_rec.py](/E:/JianYingApi/VideoFactory/scripts/decrypt_runtime_rec.py)
- [capture_real_gg_runtime_payload.py](/E:/JianYingApi/VideoFactory/scripts/capture_real_gg_runtime_payload.py)

Example:

```powershell
python scripts/decrypt_runtime_rec.py `
  "E:\JianYingApi\VideoFactory\build\reverse_capture\4y3_1_runtime_capture.rec" `
  2342914480001006 `
  --out "E:\JianYingApi\VideoFactory\build\reverse_capture\4y3_1_runtime_capture.decrypted_utf8.json"
```

Real-app capture can now be repeated through CDP:

```powershell
venv\Scripts\python.exe scripts\capture_real_gg_runtime_payload.py `
  "E:\jycaogao\JianYingPro Drafts\4月3日 (1)\draft_content.json" `
  --cdp-url "http://127.0.0.1:9222" `
  --report-json "E:\JianYingApi\VideoFactory\build\reverse_capture\runtime_capture.report.json" `
  --rec-out "E:\JianYingApi\VideoFactory\build\reverse_capture\runtime_capture.rec" `
  --json-out "E:\JianYingApi\VideoFactory\build\reverse_capture\runtime_capture.decrypted_utf8.json"
```

## Updated Reader Boundary

What is now fully confirmed:

- `draft_content.json` container -> `cppreader` -> `.rec` hex text
- `.rec` hex text -> AES-ECB(`md5(k6)`) -> JSON

What is no longer unresolved:

- the encrypted `draft_content.json` container format itself has been reproduced in-process
- the project can now decode and encode official payload containers without `p.js`, `cppreader.exe`, or GG runtime config for the tested format

## Narrowed Environment Gap

Additional direct evidence collected after the first runtime capture:

- real GG runtime launches `cppreader.exe` with this command shape:
  - `cppreader.exe <k6> <api_param> <draft_content.json> <g6_token> gg-jy-assistant <utilsPath> <userDataPath>`
- the captured real command used:
  - executable: `D:\gg-jy-assistant\resources\enhance\win32\x64\cppreader.exe`
  - `utilsPath`: `D:\gg-jy-assistant\resources\app.asar\build\electron\utils`
  - `userDataPath`: `C:\Users\Admin\AppData\Roaming\gg-jy-assistant`
- two stronger negative controls have now been proven:
  - running `cppreader.exe` directly with the exact captured argv still returns `0` and produces no `.rec`
  - launching `cppreader.exe` with GG main process as spoofed parent process still returns `0` and produces no `.rec`

Updated conclusion:

- `cppreader.exe` is only a thin launcher around a bundled Java entrypoint, not the real decrypt implementation
- the previous "return 0 but no .rec" standalone failures were partly false negatives caused by using `resources/app_source/...` instead of the semantic `resources/app.asar/...` utils path and by PowerShell/Python stdin Unicode path issues

Real launch chain observed by Frida:

```text
cppreader.exe
  -> javaw.exe -jar exempt_US_export.policy <utilsPath> <g6_token> <infoPath> <softwareKeyName> <userDataPath> <api_param> <k6>
```

The disguised JAR entrypoint is `com.bilibili.BCut`, and the actual decrypt path is delegated to `libmiddle-bridge.so` through unidbg.

Relevant helper artifacts:

- [frida_trace_cppreader.py](/E:/JianYingApi/VideoFactory/scripts/frida_trace_cppreader.py)
- [DumpBcutOffsets.java](/E:/JianYingApi/VideoFactory/scripts/DumpBcutOffsets.java)
- [frida_cppreader_standalone_v2.jsonl](/E:/JianYingApi/VideoFactory/build/reverse_capture/frida_cppreader_standalone_v2.jsonl)

## Official Container Format

The encrypted official `draft_content.json` payload is a custom container around AES-GCM:

1. Read the file as UTF-8 text.
2. Extract 8 key chunks and 4 IV chunks, each 4 characters long, from absolute offsets:
   - key offsets: `0, 7, 20, 33, 40, 47, 59, 66`
   - IV offsets: `76, 89, 99, 127`
3. Remove those 12 chunks from the container text.
4. Base64-decode the remaining body.
5. Split decoded bytes into `ciphertext || 16-byte GCM tag`.
6. Decrypt with `AES-GCM(key=<32 ASCII chars>, nonce=<16 ASCII chars>)`.
7. Parse plaintext UTF-8 JSON.

The writer is the exact inverse:

- serialize payload JSON
- generate 32 ASCII key chars and 16 ASCII IV chars
- AES-GCM encrypt
- append auth tag
- Base64 encode
- reinsert the 12 key/IV chunks at the same offsets

This has been implemented in:

- [official_draft_replace_service.py](/E:/JianYingApi/VideoFactory/app/services/jianying/official_draft_replace_service.py)

Current local reader/writer diagnostics:

- reader: `official_inprocess_aesgcm`
- writer: `official_inprocess_aesgcm`

## Implications For Rebuild

What can be treated as already understood:

- reader entrypoint: `p.js`
- state keys consumed by reader
- `cppreader.exe` argv shape and its Java/unidbg handoff
- encrypted container decode/encode rule for `draft_content.json`
- `.rec` decrypt rule: `aes-128-ecb(md5(k6))`
- writer helper behavior in `p.js`

What still requires real Jianying-side validation:

- whether the newly generated self-encoded probe opens without "linked media missing"
- whether any extra hidden cache registration is needed beyond cloning `Resources/templateDraft/vf...` and rewriting plain/encrypted payload mirrors to that root

## Next Reverse Priorities

1. Run one manual Jianying open-test on the latest self-encoded probe.
2. If media still reports missing, diff the cloned `vf...templateDraft` cache against the original cache directory and inspect whether `template_path_log.json` or root registration has hidden machine-local invariants.
3. If the probe opens cleanly, remove the stale GG runtime fallback path from the production flow in a staged branch.

## Writer Reconstruction Update

The current local writer path in [official_draft_replace_service.py](/E:/JianYingApi/VideoFactory/app/services/jianying/official_draft_replace_service.py) has been pushed closer to the runtime-decrypted payload shape:

- nested official `templateDraft` roots are cloned into local JianYing cache roots under `Resources/templateDraft/vf...`
- nested `materials.videos[*].path` values are externalized to absolute `templateDraft/.../video/...` paths
- nested `mutable_config.mutable_materials[*].cover_path` values are externalized to absolute `templateDraft/.../video/cover/...` paths
- placeholder filenames are preserved
- `retouch_cover.frame_segment_id` and `frame_timestamp` are preserved
- post-write sanitizers no longer collapse official nested cache payloads back into draft-relative paths

Current best generated candidate for manual JianYing open-test:

- [vf_probe_4y3_1_recanon_003](/E:/jycaogao/JianYingPro%20Drafts/vf_probe_4y3_1_recanon_003)

Latest reconstruction state:

- encrypted `draft_content.json` is now written by the in-process AES-GCM container encoder
- timeline `template.json` plain mirrors now reuse the same `vf...templateDraft` clone root as the encrypted payload
- regression scanner can now read encrypted `draft_content.json` through the in-process decoder

Latest automated report:

- [current_inprocess_selfwriter_mirrorfix_4y3_1.json](/E:/JianYingApi/VideoFactory/build/official_draft_regression/current_inprocess_selfwriter_mirrorfix_4y3_1.json)
