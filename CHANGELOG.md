# Changelog

## 1.0.19 - 2026-08-08

- Restored the complete NumPy runtime and preprocessing assets.
- Restored multimodal prediction and report generation.
- Removed runtime checksum enforcement while retaining structural array validation.
- Fixed the required empty input for the model-information STDIO smoke call.



## 1.0.18 - 2026-08-08

- 修复魔搭部署失败根因：uvx 要求包名与 console script 同名才能通过 `uvx <包名>` 启动；已将 console script 从 `crc-lnm-medical-agent` 改为 `crc-lnm-medical-agent-twomeme-17`，与包名一致。
- 魔搭配置改为无版本号 `crc-lnm-medical-agent-twomeme-17`（魔搭不识别 `uvx <包名>@版本` 形式），新包唯一版本 1.0.18。
- 因 PyPI 上 1.0.17 已存在（旧 console script），重新发布 1.0.18。


## 1.0.17 - 2026-08-08

- 修复 6 个工具文件 TOOL_DESCRIPTION 的 UTF-8 编码损坏（字符串未闭合导致 SyntaxError，魔搭部署检测失败退化为"仅可本地使用"），按原始语义恢复中文描述并修正特征维度（1409/768）。
- 版本升级到 1.0.17 并需重新发布 PyPI；modelscope-mcp.json / README 配置统一指向 @1.0.17。
- 目标：通过魔搭"可托管部署"STDIO 检测（uvx 包名 → initialize → list_tools）。


## 1.0.16 �?2026-08-07

- **Tool 签名回滚�?GitHub v1.0.12 风格**：重新使�?`Literal["1.1.0"]` + `UUID4` + Pydantic BaseModel 嵌套输入 (`input: PredictMultimodalInput` / `input: CaseQCInput` / �?，这�?ModelScope STDIO 通过 FastMCP 2.14.7 验证可加载的唯一签名组合�?- **保留 v1.0.16 的中�?description 字段**�? 个工具的 `TOOL_DESCRIPTION` 字符串保持不变；`mcp.tool(name=TOOL_NAME, description=TOOL_DESCRIPTION)` �?`register()` 中继续使用�?- **测试脚本同步**：smoke 客户端改为嵌�?`input: { ... }` 调用 (例如 `input: { qc_artifact_id, source: { mode: "precomputed" } }`)�?- **`package_version` / `service_version` 升级�?1.0.16**；GitHub Actions workflow 文件名替换为 `release-matrix-1.0.16.yml`，跨平台矩阵全绿�?
## 1.0.16 �?2026-08-06

- Bumped every version reference (`pyproject.toml`, GitHub Actions workflow filename + artifact path, `scripts/check_release.py` constants, `modelscope-mcp.json`, the six tools and `runtime.py` provenance) from 1.0.14 to 1.0.16.
- Replaced `.github/workflows/release-matrix-1.0.14.yml` with `release-matrix-1.0.16.yml`; the new workflow is the only one that runs on `main` pushes.
- Updated `scripts/smoke_common.py` call arguments to match the v1.0.14+ flat parameter signatures (no nested `input`, `clinical_age` / `clinical_male` / `clinical_type` / `clinical_t` at the top level), so the cross-platform smoke gate no longer fails with Pydantic `Unexpected keyword argument`.
- README and ModelScope config updated to install `crc-lnm-medical-agent-twomeme@1.0.16`.

## 1.0.14 �?2026-08-06

- Flattened all six tool signatures: `UUID4` / `Literal` / Pydantic nested `BaseModel` parameters replaced with native `str` / `int` / `float` parameters wrapped in `Annotated[Type, Field(description=...)]`.
- Clinical inputs split into four top-level parameters (`clinical_age`, `clinical_male`, `clinical_type`, `clinical_t`) instead of a nested `clinical` object.
- Each tool now exposes a stable Chinese `description` and parameter-level `description` metadata so JSON-RPC clients (e.g. Nexent) parse the schema without `anyOf` / `pattern` complications.
- Result envelopes still carry `provenance.service_version = "1.0.14"`; cross-platform smoke gate and `check_release.py` aligned with the new parameter layout.

## 1.0.11 �?2026-08-04

- Added an isolated two-tool ModelScope STDIO deployment canary.
- Reduced direct runtime dependencies to FastMCP and Pydantic and broadened Python support to 3.10+.
- Restricted the wheel to `crc_lnm_mcp`; excluded medical models, cases, old runtime code, HTTP server code,
  Docker configuration, caches, and duplicate assets.
- Replaced duplicate/version-pinned ModelScope configurations with one minimal root configuration.
- Added real MCP client smoke testing, wheel/release checks, manual deployment instructions, and rollback guidance.
- Preserved the existing six-tool medical source for a later lazy-runtime migration; it is not enabled here.