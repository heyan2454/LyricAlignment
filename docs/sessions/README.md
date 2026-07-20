# Sessions

本目录保存阶段讨论、决策依据、归档和交接记录。session 允许记录当时尚未稳定的判断，但必须标注日期和结论强度。

- `SESSION_INDEX.md`：session 索引、温度和简述。
- `_templates/`：session 模板。
- `YYYYMMDD_<topic>.md`：具体 session 记录。

温度表示读取优先级：

- `hot`：当前执行直接依赖；
- `warm`：决策仍有效，但通常无需每次全文读取；
- `cold`：已被稳定文档吸收，仅供历史追溯。

当内容已经稳定为长期约束时，迁移到 `docs/principles.md` 或 `docs/manual/`；状态事实迁移到 `docs/status/project_current.md`。session 本身保留讨论过程，避免重复作为当前事实源。
