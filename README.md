# CRC-LNM Medical Agent 1.0.19

面向 ModelScope 托管 STDIO 的完整懒加载纯 NumPy 单模型版本。一个 console script、一个进程内注册六个医学工具；initialize 和 tools/list 不读取模型参数或展开病例。第一次 `crc_lnm_predict_multimodal` 调用校验并加载唯一的 `seed_2024` NumPy runtime asset，后续预测复用同一实例。默认安装不依赖 PyTorch、NVIDIA 或 CUDA 包。

## 更新说明 (v1.0.19)

- **发布到原 PyPI 项目**：发行包名称统一为 `crc-lnm-medical-agent`。
- **console script 与包名一致**：正式启动命令统一为 `crc-lnm-medical-agent`。
- **版本升级到 1.0.19**：包含已修复的 NumPy 模型和预处理资产。
- **ModelScope 配置同步**：使用 `uvx crc-lnm-medical-agent` 启动服务。

## 功能列表

| 工具 | 功能说明 |
|------|----------|
| `crc_lnm_get_model_info` | 获取 CRC-LNM 单模型部署的元数据信息，包括模型 ID、版本、阈值、训练参数等 |
| `crc_lnm_case_data_qc` | 对结直肠癌病例数据进行质量控制检查，验证临床信息、CT 影像特征和病理特征的完整性和一致性 |
| `crc_lnm_prepare_ct_features` | 准备结直肠癌病例的 CT 影像特征，提取并验证 1409 维 CT 特征向量 |
| `crc_lnm_prepare_pathology_features` | 准备结直肠癌病例的病理特征，提取并验证 768 维病理特征向量 |
| `crc_lnm_predict_multimodal` | 基于 CT 影像特征、病理特征和临床信息进行结直肠癌淋巴结转移预测 |
| `crc_lnm_generate_report` | 生成基于质控结果和预测结果的综合研究报告 |

## ModelScope 正式配置

```json
{
  "mcpServers": {
    "crc-lnm-medical-agent": {
      "command": "uvx",
      "args": [
        "crc-lnm-medical-agent"
      ]
    }
  }
}
```

ModelScope 中选择托管部署和 STDIO；command 填 `uvx`，args 只填上面一个纯包名参数（**不带版本号**）。不要增加 URL、host、port、transport 参数或环境变量。

## 本地验收

```powershell
powershell -ExecutionPolicy Bypass -File scripts/release_verify_full.ps1
```

六工具为模型信息、病例质控、CT 特征准备、病理特征准备、单模型预测和报告生成。内置病例仅为合成演示资源；本包只用于科研辅助，不构成诊断，所有输出均需专家复核。
