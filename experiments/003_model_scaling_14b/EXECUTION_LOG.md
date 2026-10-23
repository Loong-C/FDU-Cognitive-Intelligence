# 第三轮执行记录

此日志记录真实部署与技术诊断。最终294次推理是否完成，以RESULTS.md和execution_audit.json为准。

1. 初次资源检查发现RTX 4060 Ti 8188MiB专用显存；系统可用内存约8.3GiB。用户自行让另一项目安全暂停后，可用内存曾升至约18.1GiB。本任务未结束用户其他进程，也未修改驱动、系统CUDA或全局Python。
2. 官方HF API确认模型revision、9,001,752,960字节和SHA-256。首次普通HTTP传输提前结束，只有2,080,530字节，校验拒绝；改为严格检查Content-Range的分块续传，最终整文件长度与SHA-256通过。失败文件和receipt保留。尝试安装的官方HF/Xet下载器仅位于outputs独立目录，最终成功下载由分块下载器完成，未纳入推理依赖。
3. 固定llama.cpp b11669真实加载成功。初始12/16层探针在reasoning_format=none模式发生`Unexpected empty grammar stack after accepting piece: <think>`，所有正式推理被阻止。增加`--reasoning off`单独仍不能解决该解析冲突。独立READY Schema探针对照证实deepseek解析格式成功且无reasoning_content，继续使用同一后端。
4. 最终使用服务端`--reasoning off`、生成和token预检均`enable_thinking=false`，响应格式为`deepseek`。该名称是llama.cpp解析格式，与模型名称无关；完整响应JSON原样保存。12/16层各6条真实合成探针均技术有效；20层在加载前因保守显存余量筛查拒绝。选择16层，详见deployment_preflight.json及其来源selection.json。
5. 初始正式smoke运行ID `pilot_qwen3_14b_q4_nonthink_v3` 的非思考探针被本地校验误拒：启用模式的真实/apply-template在deepseek解析下结束于assistant前缀，`<think>`由后端生成前缀处理，而不是出现在返回prompt末尾。关闭模式已返回明确的空且闭合think块，真实生成没有reasoning。修正校验后保留旧失败证据，改用r2。
6. r2真实非思考/Schema/长度探针和6条smoke通过；固定8次开发题性能探针生成621tokens，累计请求125.206秒。正式门槛读取包含非ASCII路径的UTF-8选择证据时，Windows默认GBK解码失败。r2正式预测数为0。修复所有新模块的文件读取编码，改用r3并重新执行全部门槛，未拼接r2/r3结果。
7. r3的非思考/Schema/长度探针、6条合成smoke和8条固定开发性能探针通过后，开始challenge/A2→challenge/B2→basic/A2→basic/B2的294次正式推理。完整输出路径为`outputs/runs/pilot_qwen3_14b_q4_nonthink_v3_r3/`。

修改前66项测试通过；本轮增加后88项测试通过。独立历史哈希复核确认1288个旧文件保持原样。这里的独立审计指独立Python进程、独立解析与统计实现，不声称外部人工审计。

推理源码逻辑对应提交44e7bca，运行时精确字节快照保存在`outputs/runtime/qwen3-14b/inference-source-r3/`。部分Windows写入文件使用CRLF，而Git按.gitattributes规范化为LF；fingerprint保存实际执行文件的字节哈希，精确续跑应使用该快照，不能将换行规范化后的文件悄悄接入已存在的运行。新checkout重新运行应使用新的run ID。
