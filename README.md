# autoperf-cli

`autoperf-cli` 是面向 ARM64/AArch64 + 华为 Ascend 显卡环境的自动化性能测试工具，用于编排服务配置修改、Docker 容器重启、JMeter 压测、脚本监控和结果归档。

JMeter 只负责发起压测请求；CPU、内存、NPU 使用率和 NPU 显存占用由自定义 shell 脚本采集。

## 适用环境

- CPU：ARM64 / AArch64
- NPU：华为 Ascend 显卡
- 服务：Docker 容器
- 压测：Apache JMeter
- Python：3.8+


## 安装

```bash
python3 -m pip install -e .
chmod +x scripts/*.sh

autoperf --help
```

将用户级安装目录加入 `PATH`：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

也可以在项目根目录直接使用模块方式运行：

```bash
python3 -m autoperf.cli --help
```

## 快速开始

完整压测示例：

```bash
autoperf run \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --service-workers 4 \
  --service-threads 8 \
  --threads 50 \
  --duration 600 \
  --output /root/test/results \
  --run-scripts /root/test/run_scripts \
  --interval 2 \
  --monitor-timeout 60 \
  --ready-log-pattern "Booting worker"
```

默认使用内置 JMX 模板 `templates/base.jmx`。运行时会复制模板到本次结果目录，只修改副本，不修改原始模板。

使用自定义 JMX：

```bash
autoperf run ... --jmx /path/to/custom.jmx
```

对已经启动好的服务压测并监控，不修改服务配置、不重启容器：

```bash
autoperf run-existing \
  --container ai-fs-serving \
  --workers 4 \
  --jmx /root/test/api_a.jmx \
  --threads 50 \
  --duration 600 \
  --output /root/test/results \
  --run-scripts /root/test/run_scripts \
  --interval 2 \
  --monitor-timeout 60 \
  --test-name api-a
```

## 执行流程

`autoperf run` 会依次完成：

1. 修改本地 `server_config.json` 中的 `workers` 和 `threads`
2. `docker cp` 到容器内 `/hexapp/conf/server_config.json`
3. 重启容器并等待服务启动
4. 复制并修改 JMX 模板
5. 启动监控脚本和 JMeter 压测
6. 保存 JMeter、监控、日志和报告文件

`--ready-log-pattern` 用于指定服务启动成功的日志关键字。容器重启后，工具会轮询：

```bash
docker logs --tail 200 <container>
```

如果最近 200 行日志中出现指定文本，就开始压测。未设置该参数时，只检查容器运行状态和进程 PID。

`autoperf run-existing` 用于服务已经按目标配置启动完成的场景，会依次完成：

1. 检查 Docker 和容器运行状态
2. 复制并修改 JMX 模板
3. 启动监控脚本和 JMeter 压测
4. 保存 JMeter、监控、日志和报告文件

该命令不需要 `--server-name`、`--server-config`、`--service-workers`、`--service-threads`，也不会执行 `docker cp`、`docker restart` 或服务启动等待。

## 常用命令

环境检查：

```bash
autoperf check \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --run-scripts scripts
```

只修改 JMX：

```bash
autoperf update-jmx \
  --jmx templates/base.jmx \
  --threads 100 \
  --duration 900
```

只修改并推送 `server_config.json`：

```bash
autoperf update-server-config \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --service-workers 4 \
  --service-threads 8 \
  --output /root/test/results \
  --restart
```

已有服务直接压测并监控（不修改server_config.json，不对容器进行docker cp、重启操作）：

```bash
autoperf run-existing \
  --container ai-fs-serving \
  --workers 4 \
  --jmx templates/base.jmx \
  --threads 100 \
  --duration 900 \
  --output /root/test/results \
  --run-scripts scripts
```

测试监控脚本：

```bash
autoperf test-monitor \
  --container ai-fs-serving \
  --workers 15 \
  --run-scripts scripts \
  --monitor-timeout 60
```

兼容旧脚本中的固定容器名：

```bash
autoperf update-scripts \
  --container ai-fs-serving \
  --run-scripts scripts
```


**参数说明：**

| 参数 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `--container` | 是 | - | 已经启动好的被压测服务 Docker 容器名。 |
| `--workers` | 是 | - | 当前服务实际运行的 worker 进程数，只用于监控脚本选择服务 PID，不会修改服务配置。 |
| `--jmx` | 否 | `templates/base.jmx` | JMeter JMX 模板或测试计划路径。工具会复制并修改副本，不修改原文件。 |
| `--threads` | 是 | - | JMeter 并发线程数，不是服务 worker 数。 |
| `--duration` | 是 | - | JMeter 压测持续时间，单位秒。 |
| `--jmeter-bin` | 否 | `jmeter` | JMeter 可执行文件名或路径。 |
| `--output` | 是 | - | 结果输出根目录，每次运行会在下面创建独立子目录。 |
| `--run-scripts` | 否 | `scripts` | 监控脚本目录，需包含 `run_cpu.sh`、`run_mem.sh`、`run_npu_usage.sh`、`run_npu_mem.sh`。 |
| `--interval` | 否 | `0.1` | 监控采样间隔，单位秒；最小有效值为 `0.05`。多 worker 场景建议 `2` 到 `5` 秒。 |
| `--monitor-timeout` | 否 | `60` | 单个监控脚本一次执行的超时时间，单位秒。 |
| `--npu-smi` | 否 | - | 预留参数，当前监控脚本默认直接调用系统中的 `npu-smi`。 |
| `--test-name` | 否 | JMX 文件名 | 本次测试名称，用于结果目录名和修改后的 JMX 文件名。 |
| `--force` | 否 | 关闭 | 如果结果目录已存在，允许继续写入；默认遇到同名目录会报错。 |

单个场景生成性能测试报告：

```bash
autoperf-report --run-dir /root/test/results/<run-directory>
```

`<run-directory>` 是一次压测的实际结果目录，不要原样输入。它通常包含 `result.jtl`、`jmeter_aggregate_report.csv` 或 `monitor/monitor.csv`。例如：

```text
/root/test/results/frocr_ai-fs-serving_4w_50jmx_600s_20260824_153000/
```

该命令会在场景目录中生成 `performance_report.html`、`performance_report.md`、`metrics.json` 和 `ai_report_prompt.txt`。Markdown 报告沿用性能测试报告的常见章节结构：引言、软硬件配置、测试参与人员、接口结果、资源分析和测试结论；HTML 继续用于交互查看。

如果需要将产品名称、版本、硬件配置、参与人和人工结论写入 Markdown 报告，可基于 `templates/performance_report_context.example.json` 建立上下文文件：

```bash
autoperf-report --run-dir /root/test/results/<run-directory> \
  --context /root/test/performance_report_context.json
```

上下文只补充本次运行不会自动采集的内容。接口指标、压测配置、资源峰值和监控图片链接仍以实际结果目录中的产物为准。

单个场景也可以同时使用报告上下文和 AI 分析：

```bash
export AUTOPERF_AI_API_KEY="your-api-key"
autoperf-report --run-dir /root/test/results/<run-directory> \
  --context /root/test/performance_report_context.json \
  --ai \
  --ai-base-url https://api.openai.com/v1 \
  --ai-model gpt-6.1-sol
```

该命令会额外生成 `ai_report.md`。`--context` 只影响 Word 风格 Markdown 报告中的产品、版本、硬件、参与人员和人工结论等补充信息，AI 请求仍严格使用本次运行生成的 `metrics.json` 数据。

多个场景批量汇总：

```bash
autoperf-batch-report --result-root /root/test/results/2.8.31
```

批量生成报告时，可以用同一份上下文模板补充所有场景的产品、版本、硬件、参与人员和人工结论：

```bash
autoperf-batch-report \
  --result-root /root/test/results/2.8.31 \
  --context /root/test/performance_report_context.json
```

批量命令也可以同时启用上下文模板和 AI 汇总：

```bash
export AUTOPERF_AI_API_KEY="your-api-key"
autoperf-batch-report \
  --result-root /root/test/results/2.8.31 \
  --context /root/test/performance_report_context.json \
  --ai \
  --ai-base-url https://api.openai.com/v1 \
  --ai-model gpt-5.6-luna
```

`--context` 会应用于每个场景的 `performance_report.md`。批量场景名称优先取各自运行目录中的 `test_name`，不会被模板中的示例 `scenario` 字段覆盖。

`--result-root` 是多个场景的共同父目录，不是某一个场景目录。命令会递归识别包含以下任一产物的目录：

- `result.jtl`
- `jmeter_aggregate_report.csv`
- `monitor/monitor.csv`


批量命令会为每个场景保留独立报告，并在结果根目录生成：

```text
performance_summary.html  # 一个文件，包含所有场景的对比和详细报告
performance_summary.json  # 所有场景的结构化汇总指标
ai_summary_prompt.txt     # 提交给 AI 的汇总分析提示词
ai_summary.md             # 启用 --ai 后生成的 AI 汇总结果
<scenario>/performance_report.md # 每个场景的 Word 风格 Markdown 报告
```

`performance_summary.html` 包含所有场景的接口明细、资源明细、自动结论和监控图片。已有 PNG 图表会内嵌到汇总 HTML 中，因此可以直接发送该 HTML 文件；页面中的“打开独立报告”链接在保留原目录结构时有效。

批量报告默认只生成提示词，不会调用网络服务。需要自动生成 AI 汇总时，显式添加 `--ai`：

```bash
export AUTOPERF_AI_API_KEY="your-api-key"
autoperf-batch-report --result-root /root/test/results/2.8.31 \
  --ai --ai-base-url https://api.openai.com/v1 --ai-model gpt-5.6-luna
```

AI 配置参数如下：

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--ai-api-key` | `AUTOPERF_AI_API_KEY` | 无 | API key；推荐使用环境变量，避免出现在 shell 历史中。 |
| `--ai-base-url` | `AUTOPERF_AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 的 base URL。 |
| `--ai-model` | `AUTOPERF_AI_MODEL` | `gpt-4o-mini` | 模型名称。 |
| `--ai-timeout` | `AUTOPERF_AI_TIMEOUT` | `120` | 请求超时时间，单位秒。 |

启用 AI 后，结果根目录会额外生成 `ai_summary.md`，并将 AI 汇总结果嵌入 `performance_summary.html`。AI 汇总分析输入单独写入 `ai_summary_prompt.txt`，不会嵌入汇总 HTML。API key 只用于请求，不会写入 HTML、JSON、prompt 或 AI 结果文件。

## 监控脚本

每次采样会并发调用 4 个脚本，并写入同一行 `monitor.csv`：

| 脚本 | 指标 | CSV 字段 | 单位 |
|---|---|---|---|
| `run_cpu.sh` | CPU 使用率 | `cpu_usage` | `%` |
| `run_mem.sh` | 内存占用 | `mem_usage` | GB |
| `run_npu_usage.sh` | NPU AICore 使用率 | `npu_usage` | `%` |
| `run_npu_mem.sh` | NPU 显存占用 | `npu_mem` | MiB |

采样间隔由 `--interval` 控制，默认 `0.1` 秒，最小有效值 `0.05` 秒。多 worker 场景建议使用 `2` 到 `5` 秒，避免监控本身影响被测服务。

脚本要求：

- 通过参数接收容器名，不写死容器名或 PID
- stdout 只输出一个数字
- 异常时输出 `0`
- CLI 调用时优先读取 `AUTOPERF_MONITOR_PIDS` 和 `AUTOPERF_MONITOR_RELATED_PIDS`

## 配置文件

当前版本只修改 `server_config.json` 中的 `workers` 和 `threads`，其他字段保持不变：

```json
{
  "use_gpu": true,
  "gpu_ids": "0",
  "gpu_mem": 20,
  "bind": "0.0.0.0:7000",
  "workers": 4,
  "threads": 8
}
```

容器内配置目录默认为 `/hexapp/conf`，目标文件为 `/hexapp/conf/server_config.json`。
`run`、`check` 和 `update-server-config` 均支持 `--container-config-dir`（也支持 `-container-config-dir`）。
旧目录结构可显式指定，例如：

```text
--container-config-dir /hexapp/ai-fs-serving/conf
```

`--server-name` 不再决定容器内配置路径；`--server-config` 仍指定宿主机上的配置文件。

配置推送后必须重启容器。容器重启后，旧的 root PID 和子进程 PID 会失效，工具会重新获取。

## 主服务调用依赖服务时的监控

压测请求发送给服务 A、A 再调用服务 B 时，在原有命令中追加
`--monitor-container 服务B容器名:进程数`，即可在同一次压测期间同时监控两个容器。
支持 `run`、`run-existing` 和 `test-monitor`，参数可重复指定以监控多个依赖容器。
主服务的进程数仍由 `--service-workers`（`run`）或 `--workers`（`run-existing`）指定。

例如对已经部署好的 A、B 进行测试，JMX 中仍配置 A 的接口：

```bash
autoperf run-existing \
  --container service-a \
  --workers 2 \
  --monitor-container service-b:4 \
  --jmx templates/base.jmx \
  --threads 10 \
  --duration 300 \
  --output results
```

两个容器须位于同一 Docker 主机，且已运行。A 调用 B 的地址、网络和服务映射须提前配置好。
依赖容器只参与监控，工具不会修改其配置或重启它。

两个容器各自采集 `cpu_usage`、`mem_usage`、`npu_mem`、`npu_usage`，输出分别为：

```text
<本次结果目录>/monitor/monitor.csv                         # 主服务 A
<本次结果目录>/monitor/monitor_report.html
<本次结果目录>/monitor/containers/service-b/monitor.csv    # 依赖服务 B
<本次结果目录>/monitor/containers/service-b/monitor_report.html
```

每个目录都会生成各自的趋势图（PNG 需要安装绘图依赖）。运行配置记录依赖容器名和进程数；
后续生成的综合 Markdown、HTML 报告及 `metrics.json` 也会包含依赖容器指标，
其中主服务保持在 `monitor`，依赖服务记录在 `container_monitors`，按容器名区分。

指标沿用现有采集口径：CPU、内存取所选 worker 的最大值，NPU 显存取匹配进程的最大值，
并非容器总量。NPU 利用率取关联芯片的最大利用率；两个服务共享芯片时可能显示相同的利用率，
不能将该数值直接视作单个容器独占的 NPU 利用率，也不应把两者相加。

单次检查两个容器的采集可使用：

```bash
autoperf test-monitor --container service-a --workers 2 --monitor-container service-b:4
```

## 输出结果

每次压测生成独立目录：

```text
<output>/<test_name>_<container>_<service_workers>w_<service_threads>t_<threads>jmx_<duration>s_<timestamp>/
```

`run-existing` 的目录名不包含 `service_threads`：

```text
<output>/<test_name>_<container>_<workers>w_<threads>jmx_<duration>s_<timestamp>/
```

主要文件：

```text
result.jtl
jmeter.log
run.log
config.json
<test_name>.modified.jmx
modified_server_config.json
jmeter_aggregate_report.html
jmeter_aggregate_report.csv
monitor/
  monitor.csv
  monitor_report.html
  cpu_usage.png
  mem_usage.png
  npu_usage.png
  npu_mem.png
scripts/
  run_cpu.sh
  run_mem.sh
  run_npu_usage.sh
  run_npu_mem.sh
```

批量报告生成后，结果根目录还会增加：

```text
performance_summary.html
performance_summary.json
ai_summary_prompt.txt
ai_summary.md             # 启用 --ai 后生成
```

`run-existing` 不会生成 `modified_server_config.json`。

`monitor_report.html` 为必产物，包含 CPU、内存、NPU 使用率和 NPU 显存曲线。安装 `matplotlib` 后会额外生成 PNG，PNG 生成失败不影响压测结果。

## 错误处理

以下关键步骤失败会终止压测：

- `server_config.json` 不存在、JSON 非法或缺少 `workers` / `threads`
- Docker、容器、容器内配置目录不可用
- `docker cp`、`docker restart` 或服务启动检查失败
- JMX 模板不存在、XML 解析失败或 JMeter 不存在

使用 `run-existing` 时，不会检查 `server_config.json`、容器内配置目录、`docker cp`、`docker restart` 或服务启动日志；它只要求容器已存在且正在运行。

监控脚本单次失败不会终止压测，对应指标写入 `0` 并记录 warning。
