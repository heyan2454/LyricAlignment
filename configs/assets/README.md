# Asset Configs

本目录只保存可提交的资产配置模板。

- `assets.example.yaml`：数据集、模型、AST 项目和共享根目录的发现/登记模板。
- `smoke_samples.example.yaml`：raw smoke 样本声明模板。

服务器真实值分别写入：

- `assets.local.yaml`
- `smoke_samples.local.yaml`

两个 local 文件必须保持 gitignored。配置只引用外部资产，不复制数据或模型到源码仓库。
