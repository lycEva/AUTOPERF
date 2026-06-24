# Claude Code 开发需求 Prompt：aarch64 + 华为 Ascend 自动化性能测试 CLI 工具

你是一个资深 Python CLI 工具开发工程师。请帮我开发一个用于 **ARM64 架构、华为 Ascend 310P NPU 环境** 下的一键自动化性能测试 CLI 工具。

---

## 一、项目基本信息

### 项目名称

`autoperf-cli`

### 项目目标

实现一个命令行工具，用于自动完成以下流程：

1. 修改服务内部并发配置 `server_config.json`；
2. 将修改后的配置文件 `docker cp` 到容器内；
3. 重启 Docker 容器，使配置生效；
4. 等待服务启动完成；
5. 容器重启后重新获取容器主进程 PID 和子进程 PID；
6. 修改 JMeter JMX 文件中的并发线程数和压测时长；
7. 启动脚本化性能监控；
8. 启动 JMeter 压测；
9. 保存 JMeter 结果、监控数据、日志、配置快照；
10. 基于监控 CSV 自动生成 HTML 图表报告。

---

## 二、项目背景

当前运行环境为：

- CPU 架构：`ARM64 / AArch64`
- 推理卡：`华为 Ascend 310P`
- 服务运行方式：`Docker 容器`
- 压测工具：`Apache JMeter`
- 监控方式：`自定义脚本采集`

由于 **JMeter 自带的 PerfMon / ServerAgent 监控插件在 ARM64 环境下不可用或兼容性较差**，因此本项目不能依赖 JMeter 自带插件采集 CPU、内存、NPU、显存等指标。

本项目需要通过 **自定义监控脚本 + CLI 调度** 的方式完成性能指标采集。

---

## 三、核心业务规则

以下规则非常重要，不能遗漏：

1. JMeter 只负责发起压测请求；
2. CLI 工具负责修改 `server_config.json`、`docker cp` 到容器、重启容器、修改 JMX、启动 JMeter、调度监控脚本、保存结果；
3. 监控指标完全通过自定义脚本采集；
4. 监控指标包括：
   - CPU 使用率；
   - 内存占用值；
   - NPU 使用率；
   - 显存占用；
5. 所有监控脚本必须通过 Docker 容器名获取容器主进程 PID；
6. 通过容器主进程 PID 递归查找其下所有子进程 PID；
7. 每次采样时都要重新获取子进程 PID；
8. 不允许写死 PID；
9. 单进程场景下，直接取该子进程指标值；
10. 多进程场景下，CPU、内存、NPU 使用率、显存占用全部取所有子进程中的最大值；
11. `server_config.json` 格式固定，当前只修改 `workers` 和 `threads`；
12. 运行 JMeter 前，必须先修改 `server_config.json`；
13. 修改 `server_config.json` 后，必须 `docker cp` 到容器内：

```bash
/hexapp/ai-<server_name>-serving/conf/server_config.json
```

14. `docker cp` 完成后，必须 `docker restart` 容器；
15. 容器重启后，必须重新获取 root PID 和子进程 PID；
16. 服务启动成功后，才能启动 JMeter；
17. 如果服务配置修改、`docker cp`、`docker restart` 或服务启动检查失败，不能继续压测；
18. 监控原始数据必须保存为 `monitor.csv`；
19. 压测结束后必须基于 `monitor.csv` 生成 `monitor_report.html` 图表报告；
20. PNG 图可选生成，不能因为 PNG 生成失败导致压测失败。

---

## 四、推荐技术栈

请使用 Python 实现，要求尽量减少第三方依赖。

推荐技术栈：

- Python 3.8+
- `argparse`：CLI 参数解析，优先使用标准库；
- `xml.etree.ElementTree`：修改 JMX 文件；
- `subprocess`：执行 Docker、JMeter、Shell 脚本；
- `csv`：保存监控数据；
- `json`：读取和保存配置；
- `logging`：日志输出；
- `pathlib`：路径处理；
- `threading`：同时运行 JMeter 和监控循环；
- `shutil`：文件复制；
- `datetime`：时间戳处理；
- `statistics`：计算监控指标统计值。

可选增强：

- `matplotlib`：如果存在，则生成 PNG 图片；如果不存在，不影响主流程。

---

## 五、项目目录结构

请生成如下项目结构：

```bash
autoperf-cli/
├── autoperf/
│   ├── __init__.py
│   ├── cli.py
│   ├── jmx_editor.py
│   ├── docker_utils.py
│   ├── service_config_editor.py
│   ├── monitor.py
│   ├── report_generator.py
│   ├── script_editor.py
│   ├── jmeter_runner.py
│   ├── env_checker.py
│   ├── config.py
│   ├── logger.py
│   └── utils.py
├── scripts/
│   ├── run_cpu.sh
│   ├── run_mem.sh
│   ├── run_npu_usage.sh
│   └── run_npu_mem.sh
├── templates/
│   └── base.jmx
├── README.md
├── requirements.txt
├── pyproject.toml
└── example_config.json
```

---

## 六、CLI 命令设计

### 1. 完整压测命令

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
  --ready-log-pattern "Booting worker"
```

### 参数说明

| 参数 | 是否必填 | 说明 |
|---|---|---|
| `--jmx` | 否 | JMeter 基础 JMX 模板路径；不传时默认使用项目内置 `templates/base.jmx` |
| `--container` | 是 | 被压测服务的 Docker 容器名 |
| `--server-name` | 是 | 服务名称，用于拼接容器内配置目录 |
| `--server-config` | 是 | 本地 `server_config.json` 文件路径 |
| `--service-workers` | 是 | 服务内部 worker 进程数，用于修改 `workers` 字段 |
| `--service-threads` | 是 | 服务内部线程数，用于修改 `threads` 字段 |
| `--threads` | 是 | JMeter 并发线程数 |
| `--duration` | 是 | JMeter 压测持续时间，单位秒 |
| `--output` | 是 | 结果输出目录 |
| `--run-scripts` | 否 | 监控脚本目录，默认 `./scripts` |
| `--jmeter-bin` | 否 | JMeter 可执行文件路径，默认 `jmeter` |
| `--interval` | 否 | 监控采样间隔，默认 1 秒 |
| `--npu-smi` | 否 | `npu-smi` 路径，可选，默认自动查找 |
| `--test-name` | 否 | 测试名称，默认使用 JMX 模板文件名 |
| `--force` | 否 | 如果输出目录已存在，是否允许覆盖 |
| `--restart-timeout` | 否 | 容器重启后等待服务恢复超时时间，默认 120 秒 |
| `--ready-log-pattern` | 否 | 用于通过 `docker logs` 判断服务是否启动成功 |
| `--ready-check-interval` | 否 | 服务启动检查间隔，默认 3 秒 |

---

### 2. 只修改 JMX

```bash
autoperf update-jmx \
  --jmx /root/test/fs_test.jmx \
  --threads 100 \
  --duration 900
```

---

### 3. 只测试监控脚本

```bash
autoperf test-monitor \
  --container ai-fs-serving \
  --run-scripts /root/test/run_scripts
```

---

### 4. 环境检查

```bash
autoperf check \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --run-scripts /root/test/run_scripts
```

---

### 5. 单独修改并推送 server_config.json

```bash
autoperf update-server-config \
  --container ai-fs-serving \
  --server-name fs \
  --server-config /root/test/server_config.json \
  --service-workers 4 \
  --service-threads 8 \
  --restart
```

如果不传 `--restart`，则只修改配置并 `docker cp`，不重启容器。

---

### 6. 兼容旧监控脚本的容器名替换命令

```bash
autoperf update-scripts \
  --container ai-fs-serving \
  --run-scripts /root/test/run_scripts
```

---

## 七、server_config.json 修改需求

### 1. 固定格式

被测服务的 `server_config.json` 格式固定如下：

```json
{
  "use_gpu": true,
  "gpu_ids": "0",
  "gpu_mem": 20,
  "bind": "0.0.0.0:7000",
  "workers": 1,
  "threads": 1
}
```

### 2. 字段说明

| 字段 | 说明 | 是否修改 |
|---|---|---|
| `use_gpu` | 是否启用 NPU/GPU 推理环境 | 不修改 |
| `gpu_ids` | 使用的设备编号 | 不修改 |
| `gpu_mem` | 显存配置值 | 不修改 |
| `bind` | 服务监听地址和端口 | 不修改 |
| `workers` | 服务内部 worker 进程数 | 修改 |
| `threads` | 服务内部线程数 | 修改 |

### 3. 修改规则

当前版本只需要修改：

```json
{
  "workers": 4,
  "threads": 8
}
```

不要修改：

```json
{
  "use_gpu": true,
  "gpu_ids": "0",
  "gpu_mem": 20,
  "bind": "0.0.0.0:7000"
}
```

### 4. 实现要求

新增模块：

```bash
autoperf/service_config_editor.py
```

功能要求：

1. 读取 `--server-config` 指定的 `server_config.json`；
2. 校验 JSON 合法性；
3. 校验必须存在 `workers` 字段；
4. 校验必须存在 `threads` 字段；
5. 将 `workers` 修改为 `--service-workers` 的值；
6. 将 `threads` 修改为 `--service-threads` 的值；
7. 其他字段必须保持不变；
8. 修改前备份原始 `server_config.json`。

备份示例：

```bash
server_config.json.bak.20260508_153000
```

9. 修改后的配置文件保存到本次结果目录，文件名为：

```bash
modified_server_config.json
```

10. `docker cp` 时需要把 `modified_server_config.json` 拷贝到容器内，并命名为 `server_config.json`。

### 5. 修改示例

原始配置：

```json
{
  "use_gpu": true,
  "gpu_ids": "0",
  "gpu_mem": 20,
  "bind": "0.0.0.0:7000",
  "workers": 1,
  "threads": 1
}
```

用户传入：

```bash
--service-workers 4
--service-threads 8
```

修改后：

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

### 6. 参数校验

`--service-workers`：

- 必须是正整数；
- 必须大于等于 1。

`--service-threads`：

- 必须是正整数；
- 必须大于等于 1。

错误提示示例：

```text
[ERROR] server_config.json missing required field: workers
[ERROR] server_config.json missing required field: threads
[ERROR] --service-workers must be a positive integer
[ERROR] --service-threads must be a positive integer
```

---

## 八、docker cp 配置文件到容器内

修改 `server_config.json` 后，CLI 需要执行 `docker cp`。

### 1. 容器内目标路径规则

```bash
/hexapp/ai-<server_name>-serving/conf/server_config.json
```

示例：

```bash
server_name = fs
```

则目标路径为：

```bash
/hexapp/ai-fs-serving/conf/server_config.json
```

### 2. docker cp 示例

```bash
docker cp \
  /root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/modified_server_config.json \
  ai-fs-serving:/hexapp/ai-fs-serving/conf/server_config.json
```

### 3. 实现要求

1. `docker cp` 前需要检查容器是否存在；
2. `docker cp` 前需要检查容器是否正在运行；
3. `docker cp` 前需要检查容器内目录是否存在；
4. 可以通过以下命令检查目录：

```bash
docker exec <container> test -d /hexapp/ai-<server_name>-serving/conf
```

5. 如果目录不存在，需要报错退出；
6. `docker cp` 失败时，需要报错退出；
7. `docker cp` 成功后，需要打印日志。

成功日志示例：

```text
[OK] docker cp completed: modified_server_config.json -> ai-fs-serving:/hexapp/ai-fs-serving/conf/server_config.json
```

---

## 九、重启容器并等待服务恢复

`server_config.json` 拷贝完成后，需要重启容器：

```bash
docker restart <container>
```

### 实现要求

1. `docker restart` 返回成功后，需要等待容器恢复 running；
2. 需要重新检查容器状态；
3. 需要重新获取容器主进程 PID；
4. 需要重新获取子进程 PID；
5. 需要等待服务启动完成后，再进入 JMeter 压测阶段；
6. 容器重启前获取到的 root PID 和子进程 PID 必须全部作废；
7. 容器重启后必须重新获取 PID。

### 服务启动检查方式

如果用户指定 `--ready-log-pattern`，则循环执行：

```bash
docker logs --tail 200 <container>
```

判断日志中是否包含指定关键字。

如果包含，则认为服务启动成功。

如果用户没有指定 `--ready-log-pattern`，则使用基础检查：

1. `docker inspect` 确认容器 running；
2. 获取容器 root PID；
3. 获取子进程 PID；
4. 等待 5 秒；
5. 进入下一步。

如果超过 `--restart-timeout` 仍未成功，则报错退出。

### 日志示例

```text
[INFO] Restarting container: ai-fs-serving
[OK] Container restarted
[INFO] Waiting service ready
[OK] Service ready
[INFO] Refreshing container PID after restart
[OK] New container root PID: 23456
[OK] Child PIDs: 23457,23458
```

---

## 十、完整运行流程

`autoperf run` 必须严格按照以下顺序执行：

1. 解析 CLI 参数；
2. 创建本次压测结果目录；
3. 初始化 `run.log`；
4. 检查 Docker 是否可用；
5. 检查容器是否存在；
6. 检查容器是否正在运行；
7. 检查 `server_config.json` 是否存在；
8. 校验 `server_config.json` 是否为合法 JSON；
9. 校验 `server_config.json` 是否包含 `workers` 和 `threads` 字段；
10. 修改 `workers` 和 `threads`；
11. 保存 `modified_server_config.json` 到结果目录；
12. 检查容器内配置目录是否存在：

```bash
/hexapp/ai-<server_name>-serving/conf
```

13. `docker cp modified_server_config.json` 到容器内：

```bash
/hexapp/ai-<server_name>-serving/conf/server_config.json
```

14. `docker restart <container>`；
15. 等待容器恢复 running；
16. 等待服务启动完成；
17. 重新获取容器 root PID；
18. 重新获取子进程 PID；
19. 检查 JMX 模板文件是否存在；如果未传 `--jmx`，则检查项目内置 `templates/base.jmx` 是否存在；
20. 复制 JMX 模板到结果目录；
21. 修改结果目录中 JMX 副本的 `threads` 和 `duration`；
22. 保存 `modified.jmx` 到结果目录；
23. 复制本次监控脚本到结果目录 `scripts/`；
24. 保存 `config.json`；
25. 启动监控循环；
26. 启动 JMeter 非 GUI 压测；
27. 等待 JMeter 执行完成；
28. 停止监控循环；
29. 保存 `monitor.csv`；
30. 基于 `monitor.csv` 生成 `monitor_report.html`；
31. 如果 `matplotlib` 可用，生成 PNG 图；
32. 保存 `result.jtl`、`jmeter.log`、`run.log`、`config.json`、`modified_server_config.json`、`modified.jmx`；
33. 输出结果目录和报告路径。

重要要求：

不能在 `server_config.json` 修改失败、`docker cp` 失败、容器重启失败、服务未启动成功的情况下继续运行 JMeter。

这些属于压测前关键步骤，失败时必须终止压测。

---

## 十一、JMX 动态修改需求

项目需要内置一个基础 JMeter JMX 模板文件：

```bash
templates/base.jmx
```

`autoperf run` 默认使用该内置模板作为基础压测脚本。用户也可以通过 `--jmx` 指定其他 JMX 模板文件覆盖默认模板。

### 0. JMX 模板处理规则

1. 不允许直接修改项目内置的 `templates/base.jmx`；
2. 不允许直接修改用户通过 `--jmx` 传入的原始 JMX 文件；
3. 每次运行时，必须先把基础 JMX 模板复制到本次结果目录；
4. 只修改结果目录中的 JMX 副本；
5. JMeter 最终执行的必须是结果目录中的 `*.modified.jmx`；
6. `config.json` 中需要同时记录：
   - `jmx_template`：本次使用的基础 JMX 模板路径；
   - `modified_jmx`：本次实际执行的修改后 JMX 路径。

需要自动修改 JMeter JMX 文件副本中的以下内容。

### 1. 修改线程数

将：

```xml
<stringProp name="ThreadGroup.num_threads">10</stringProp>
```

修改为用户传入的 `--threads`。

### 2. 修改压测时长

将：

```xml
<stringProp name="ThreadGroup.duration">300</stringProp>
```

修改为用户传入的 `--duration`。

### 3. 确保 scheduler 开启

如果 JMX 中存在：

```xml
<boolProp name="ThreadGroup.scheduler">false</boolProp>
```

需要改为：

```xml
<boolProp name="ThreadGroup.scheduler">true</boolProp>
```

如果不存在，可以不强制新增，但需要日志提示。

### 4. 不修改原始 JMX

由于 JMX 采用模板方式管理，修改前不需要覆盖或备份原始 JMX。

实现时必须先复制模板文件，再修改复制后的文件。

### 5. 保存修改后的 JMX

修改后的 JMX 需要复制一份到结果目录，命名为：

```bash
fs_test.modified.jmx
```

---

## 十二、Docker 容器进程识别需求

需要实现：

```bash
autoperf/docker_utils.py
```

支持以下功能：

1. 判断 Docker 是否可用；
2. 判断容器是否存在；
3. 判断容器是否正在运行；
4. 获取容器主进程 PID：

```bash
docker inspect -f '{{.State.Pid}}' <container>
```

5. 根据容器主进程 PID 递归获取所有子进程 PID。

Shell 逻辑类似：

```bash
get_children() {
  local parent_pid=$1
  for child_pid in $(pgrep -P "$parent_pid"); do
    echo "$child_pid"
    get_children "$child_pid"
  done
}
```

Python 中可以通过 `subprocess` 调用：

```bash
pgrep -P <pid>
```

也可以读取：

```bash
/proc/<pid>/task/<pid>/children
```

### 要求

1. 每次采样都重新获取容器主进程和子进程；
2. 不允许固定 PID；
3. 子进程为空时返回空列表，并记录 warning，不要让程序崩溃；
4. 容器重启后必须重新获取 root PID 和子进程 PID。

---

## 十三、监控指标采集需求

因为 JMeter 自带监控插件不支持当前 ARM64 环境，所以需要通过脚本监控。

### 需要监控的指标

1. CPU 使用率；
2. 内存占用值；
3. NPU 使用率；
4. 显存占用。

### 所有指标统一规则

1. 先通过容器名获取容器主进程 PID；
2. 再递归获取主进程下所有子进程 PID；
3. 分别采集每个子进程的指标；
4. 如果是多进程，取所有子进程中的最大值；
5. 如果是单进程，直接取该子进程的值；
6. 如果获取失败，输出 0；
7. 输出必须是纯数字，不带单位、不带中文、不带日志；
8. 每次采样都要重新获取 PID。

### 示例

某次采样有 4 个子进程：

| PID | CPU | Memory MiB | NPU Usage | NPU Mem MiB |
|---|---:|---:|---:|---:|
| 1001 | 35 | 512 | 20 | 1024 |
| 1002 | 70 | 2048 | 45 | 4096 |
| 1003 | 120 | 1536 | 80 | 3072 |
| 1004 | 55 | 1024 | 60 | 2048 |

最终输出：

```text
CPU 使用率：120
内存占用：2048
NPU 使用率：80
显存占用：4096
```

注意：

不同指标的最大值可以来自不同子进程。

---

## 十四、监控脚本需求

请生成以下 4 个 shell 脚本，放在 `scripts/` 目录下。

```bash
scripts/
├── run_cpu.sh
├── run_mem.sh
├── run_npu_usage.sh
└── run_npu_mem.sh
```

4 个脚本与监控指标的对应关系固定如下：

| 脚本 | 指标 | 输出含义 |
|---|---|---|
| `run_cpu.sh` | CPU 使用率 | 容器服务子进程 CPU 使用率，单进程取该进程值，多进程取最大值 |
| `run_mem.sh` | 内存占用 | 容器服务子进程内存占用，单进程取该进程值，多进程取最大值 |
| `run_npu_usage.sh` | NPU 使用率 | 容器服务子进程 NPU 使用率，单进程取该进程值，多进程取最大值 |
| `run_npu_mem.sh` | 显存占用 | 容器服务子进程 NPU 显存占用，单进程取该进程值，多进程取最大值 |

`monitor.py` 必须按采样间隔循环调用这 4 个脚本，并把结果写入 `monitor/monitor.csv`。

### 所有脚本通用要求

1. 使用 bash；
2. 支持通过参数传入容器名：

```bash
./run_cpu.sh <container>
```

3. 不能写死容器名；
4. 不能写死 PID；
5. 每次执行都要重新获取容器 root PID 和子进程 PID；
6. 多进程取最大值；
7. 单进程取该进程值；
8. 异常时输出 `0`；
9. 只输出一个数字；
10. 不输出单位；
11. 不输出日志；
12. 不输出中文；
13. 不输出多余空行；
14. 脚本内部可以使用 stderr 输出调试信息，但默认不要输出；
15. 需要在 README 中说明如何添加执行权限：

```bash
chmod +x scripts/*.sh
```

---

### 1. run_cpu.sh

用途：

根据容器名获取子进程 PID，采集每个子进程的 CPU 使用率，返回最大值。

调用方式：

```bash
./run_cpu.sh ai-fs-serving
```

输出示例：

```text
120
```

要求：

- 输出纯数字；
- 不带 `%`；
- 多进程取最大值；
- 单进程取该进程值；
- 异常输出 `0`。

CPU 可以使用：

```bash
ps -p <pid> -o %cpu=
```

或 `top` 方式。

---

### 2. run_mem.sh

用途：

根据容器名获取子进程 PID，采集每个子进程的内存占用，返回最大值。

调用方式：

```bash
./run_mem.sh ai-fs-serving
```

输出示例：

```text
2048
```

要求：

- 输出纯数字；
- 单位使用 MiB；
- 多进程取最大值；
- 单进程取该进程值；
- 异常输出 `0`。

优先使用：

```bash
/proc/<pid>/smaps_rollup
```

读取 `Pss` 字段，单位 kB，然后转换为 MiB。

如果 `smaps_rollup` 不存在，则使用：

```bash
ps -p <pid> -o rss=
```

同样转换为 MiB。

---

### 3. run_npu_usage.sh

用途：

根据容器名获取子进程 PID，采集华为 Ascend 310P 的 NPU 使用率，返回最大值。

调用方式：

```bash
./run_npu_usage.sh ai-fs-serving
```

输出示例：

```text
80
```

要求：

- 输出纯数字；
- 不带 `%`；
- 多进程取最大值；
- 单进程取该进程值；
- 异常输出 `0`。

`npu-smi` 路径可能是：

```bash
/usr/local/Ascend/driver/tools/npu-smi
/usr/local/bin/npu-smi
npu-smi
```

需要脚本中自动查找。

NPU 使用率可以尝试通过以下命令解析：

```bash
npu-smi info -t usages -i <card_id> -c <chip_id>
```

从输出中解析：

```text
Aicore Usage Rate
```

或类似字段。

如果无法准确按 PID 关联 AICore 使用率，可以先实现为：

1. 找到所有 NPU 设备；
2. 读取每个设备的 AICore 使用率；
3. 返回最大值；
4. 代码中保留 TODO，后续支持 PID 到 card/chip 的精确映射。

---

### 4. run_npu_mem.sh

用途：

根据容器名获取子进程 PID，采集华为 Ascend 310P 显存占用，返回最大值。

调用方式：

```bash
./run_npu_mem.sh ai-fs-serving
```

输出示例：

```text
4096
```

要求：

- 输出纯数字；
- 单位 MiB；
- 多进程取最大值；
- 单进程取该进程值；
- 异常输出 `0`。

可以尝试使用：

```bash
npu-smi info -t proc-mem -i <card_id>
```

根据 PID 匹配容器子进程，解析对应显存占用。

如果一个 PID 出现在多个设备上，取最大值。

如果多个子进程都有显存占用，最终取最大值。

---

## 十五、CLI 调度监控脚本需求

需要实现：

```bash
autoperf/monitor.py
```

### 功能要求

1. 启动监控循环；
2. 每 `interval` 秒调用一次 4 个脚本：
   - `run_cpu.sh`
   - `run_mem.sh`
   - `run_npu_usage.sh`
   - `run_npu_mem.sh`
3. 每次采样写入 `monitor.csv`；
4. JMeter 结束后停止监控循环；
5. 如果某个脚本执行失败，该指标记为 `0`，并记录 warning；
6. 监控循环不能因为某个脚本失败而退出；
7. `subprocess` 调用脚本时要设置 timeout，避免脚本卡死；
8. 如果脚本输出非数字，则该指标记为 `0`，并记录 warning。

### monitor.csv 格式

```csv
timestamp,cpu_usage,mem_usage_mib,npu_usage,npu_mem_mib
2026-05-08 15:30:01,120,2048,80,4096
2026-05-08 15:30:02,115,2050,75,4090
```

保存路径：

```bash
<output_dir>/monitor/monitor.csv
```

---

## 十六、监控图表报告需求

CSV 可以保存原始监控数据，但不方便直接查看趋势图。

因此需要在压测结束后，基于 `monitor.csv` 自动生成图表报告。

### 1. 核心要求

1. `monitor.csv` 必须保留，作为原始监控数据；
2. 压测结束后，需要自动生成监控图表；
3. 图表需要展示以下指标随时间变化的趋势：
   - CPU 使用率；
   - 内存占用 MiB；
   - NPU 使用率；
   - 显存占用 MiB；
4. 图表报告需要保存到结果目录；
5. 必须生成 HTML 报告，方便直接用浏览器打开；
6. 可选生成 PNG 图片，方便截图或放到测试报告中。

### 2. 新增输出文件

```bash
<output_dir>/
├── monitor/
│   ├── monitor.csv
│   ├── monitor_report.html
│   ├── cpu_usage.png
│   ├── mem_usage.png
│   ├── npu_usage.png
│   └── npu_mem.png
```

### 3. 新增模块

```bash
autoperf/report_generator.py
```

### 4. HTML 报告要求

优先实现 HTML 报告。

为了减少第三方依赖，可以直接生成一个独立的 HTML 文件。

HTML 中可以使用内嵌 JavaScript 和 SVG / Canvas 展示折线图。

要求：

1. `monitor_report.html` 可以直接双击打开；
2. 不依赖外网；
3. 不引用 CDN；
4. 所有数据直接内嵌在 HTML 文件中；
5. 展示 4 张折线图：
   - CPU 使用率趋势图；
   - 内存占用趋势图；
   - NPU 使用率趋势图；
   - 显存占用趋势图；
6. 页面顶部展示本次测试信息：
   - container；
   - server_name；
   - service_workers；
   - service_threads；
   - JMeter threads；
   - duration；
   - start_time；
7. 页面展示每个指标的统计值：
   - max；
   - min；
   - avg；
8. HTML 报告标题：

```text
AutoPerf Monitor Report
```

### 5. 图表要求

1. X 轴：时间；
2. Y 轴：指标数值；
3. 每个指标单独一张图；
4. 图表上方显示指标名称；
5. 图表下方显示 max / min / avg；
6. 数据为空时，页面显示：

```text
No monitor data available.
```

### 6. PNG 图片，可选增强

如果环境安装了 `matplotlib`，可以额外生成 PNG 图片：

```bash
cpu_usage.png
mem_usage.png
npu_usage.png
npu_mem.png
```

要求：

1. 如果 `matplotlib` 不存在，不要让程序失败；
2. 只打印 warning；
3. HTML 报告仍然必须生成；
4. PNG 生成属于增强功能，不是关键流程。

### 7. report_generator.py 函数要求

需要提供函数：

```python
generate_monitor_report(
    monitor_csv_path,
    output_dir,
    config_json_path=None
)
```

功能：

1. 读取 `monitor.csv`；
2. 解析：
   - `timestamp`
   - `cpu_usage`
   - `mem_usage_mib`
   - `npu_usage`
   - `npu_mem_mib`
3. 计算每个指标的：
   - max；
   - min；
   - avg；
4. 生成 `monitor_report.html`；
5. 如果 `matplotlib` 可用，生成 4 张 PNG 图；
6. 返回生成的报告路径。

### 8. 异常处理

1. 如果 `monitor.csv` 不存在，打印 warning，不终止压测；
2. 如果 `monitor.csv` 为空，生成 HTML，但提示 `No monitor data available.`；
3. 如果某些字段缺失，打印 warning；
4. 如果 PNG 生成失败，不影响 HTML 报告生成；
5. 生成报告失败不能删除已有压测结果。

### 9. 压测完成输出示例

```text
[OK] Performance test completed
[OK] Monitor CSV: /root/test/results/.../monitor/monitor.csv
[OK] Monitor report: /root/test/results/.../monitor/monitor_report.html
[OK] Result JTL: /root/test/results/.../result.jtl
[OK] JMeter log: /root/test/results/.../jmeter.log
```

---

## 十七、JMeter 启动需求

需要使用非 GUI 模式启动 JMeter：

```bash
jmeter -n \
  -t <modified_jmx> \
  -l <output_dir>/result.jtl \
  -j <output_dir>/jmeter.log
```

### 要求

1. 启动前检查 JMeter 是否存在；
2. 压测过程中实时输出 JMeter 日志到 `run.log`；
3. JMeter 返回码非 0 时，需要打印错误；
4. 无论成功还是失败，都要保留：
   - `result.jtl`
   - `jmeter.log`
   - `monitor.csv`
   - `config.json`
   - `run.log`
5. 监控循环需要在 JMeter 开始前启动，在 JMeter 结束后停止；
6. JMeter 执行失败不能删除结果目录。

---

## 十八、结果目录要求

每次压测需要生成独立目录，格式：

```bash
<output>/<test_name>_<container>_<service_workers>w_<service_threads>t_<threads>jmx_<duration>s_<timestamp>/
```

示例：

```bash
/root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/
```

### 目录结构

```bash
fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/
├── result.jtl
├── jmeter.log
├── run.log
├── config.json
├── fs_test.modified.jmx
├── modified_server_config.json
├── monitor/
│   ├── monitor.csv
│   ├── monitor_report.html
│   ├── cpu_usage.png
│   ├── mem_usage.png
│   ├── npu_usage.png
│   └── npu_mem.png
└── scripts/
    ├── run_cpu.sh
    ├── run_mem.sh
    ├── run_npu_usage.sh
    └── run_npu_mem.sh
```

### 要求

1. 本次使用的监控脚本要复制到结果目录 `scripts/` 下；
2. 本次修改后的 JMX 要复制到结果目录；
3. 本次修改后的 `server_config.json` 要保存到结果目录；
4. 本次运行参数保存到 `config.json`；
5. 所有日志保存到 `run.log`；
6. 监控原始数据保存到 `monitor/monitor.csv`；
7. 监控图表报告保存到 `monitor/monitor_report.html`；
8. PNG 图片可选保存到 `monitor/` 目录。

### config.json 示例

```json
{
  "jmx_template": "templates/base.jmx",
  "modified_jmx": "/root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/fs_test.modified.jmx",
  "container": "ai-fs-serving",
  "server_name": "fs",
  "server_config": "/root/test/server_config.json",
  "modified_server_config": "/root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/modified_server_config.json",
  "container_config_path": "/hexapp/ai-fs-serving/conf/server_config.json",
  "service_workers": 4,
  "service_threads": 8,
  "threads": 50,
  "duration": 600,
  "interval": 1,
  "jmeter_bin": "jmeter",
  "run_scripts": "/root/test/run_scripts",
  "output_dir": "/root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000",
  "monitor_csv": "/root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/monitor/monitor.csv",
  "monitor_report": "/root/test/results/fs_test_ai-fs-serving_4w_8t_50jmx_600s_20260508_153000/monitor/monitor_report.html",
  "container_restarted": true,
  "start_time": "2026-05-08 15:30:00"
}
```

---

## 十九、环境检查命令需求

`autoperf check` 需要检查：

1. Python 版本；
2. Docker 是否可用；
3. 容器是否存在；
4. 容器是否正在运行；
5. 是否能获取容器主进程 PID；
6. 是否能获取子进程 PID；
7. `server_config.json` 是否存在；
8. `server_config.json` 是否为合法 JSON；
9. `server_config.json` 是否包含 `workers` 字段；
10. `server_config.json` 是否包含 `threads` 字段；
11. 容器内目标目录是否存在：

```bash
/hexapp/ai-<server_name>-serving/conf
```

12. JMX 模板文件是否存在；如果未传 `--jmx`，则检查项目内置 `templates/base.jmx`；
13. JMeter 是否可执行；
14. 监控脚本目录是否存在；
15. 4 个监控脚本是否存在；
16. 4 个监控脚本是否有执行权限；
17. `npu-smi` 是否存在；
18. 是否可以执行一次监控脚本并得到纯数字；
19. 是否有权限执行 `docker cp` 的基础检查；
20. 默认不要真的重启容器。

如果需要真实测试重启，增加参数：

```bash
--check-restart
```

只有传入 `--check-restart` 时，才允许执行 `docker restart` 测试。

### 输出示例

```text
[OK] Python version: 3.8.10
[OK] Docker available
[OK] Container exists: ai-fs-serving
[OK] Container running
[OK] Container root PID: 12345
[OK] Child PIDs: 12346,12347
[OK] server_config.json exists
[OK] server_config.json valid
[OK] server_config.json field exists: workers
[OK] server_config.json field exists: threads
[OK] Container config dir exists: /hexapp/ai-fs-serving/conf
[OK] JMX template exists: templates/base.jmx
[OK] JMeter available: /opt/jmeter/bin/jmeter
[OK] Monitor script: run_cpu.sh
[OK] Monitor script: run_mem.sh
[OK] Monitor script: run_npu_usage.sh
[OK] Monitor script: run_npu_mem.sh
[OK] npu-smi found
[OK] Monitor test passed
```

---

## 二十、脚本容器名处理需求

监控脚本应优先支持通过参数传入容器名：

```bash
./run_cpu.sh <container>
```

不建议写死 `container` 变量。

但 CLI 可以额外提供 `update-scripts` 命令，用于兼容旧脚本中写死容器名的情况。

需要支持替换以下格式：

```bash
container=old_name
CONTAINER=old_name
docker inspect old_name
docker top old_name
```

替换成用户指定的新容器名。

命令：

```bash
autoperf update-scripts \
  --container ai-fs-serving \
  --run-scripts /root/test/run_scripts
```

---

## 二十一、日志要求

日志需要清晰，包括：

```text
[INFO] AutoPerf started
[INFO] Parsing arguments
[INFO] Creating result directory
[INFO] Checking Docker
[INFO] Checking container
[INFO] Updating service config
[INFO] server_config.json: /root/test/server_config.json
[INFO] service workers: 4
[INFO] service threads: 8
[OK] modified_server_config.json generated
[INFO] Copying server config to container
[OK] docker cp completed
[INFO] Restarting container: ai-fs-serving
[OK] Container restarted
[INFO] Waiting service ready
[OK] Service ready
[INFO] Refreshing container PID after restart
[OK] New container root PID: 23456
[INFO] Updating JMX
[OK] ThreadGroup.num_threads updated
[OK] ThreadGroup.duration updated
[INFO] Starting monitor loop
[INFO] Starting JMeter
[WARN] Monitor script failed: run_npu_usage.sh
[INFO] Generating monitor report
[OK] Monitor report generated
[ERROR] JMeter failed
[OK] Performance test completed
```

异常不能只抛 traceback，需要给出用户可读的错误说明。

详细 traceback 可以写入 `run.log`，但控制台要输出清晰错误。

---

## 二十二、异常处理需求

需要覆盖以下情况：

1. Docker 不存在；
2. 容器不存在；
3. 容器未运行；
4. 获取 root PID 失败；
5. 子进程为空；
6. `server_config.json` 不存在；
7. `server_config.json` 不是合法 JSON；
8. `server_config.json` 缺少 `workers`；
9. `server_config.json` 缺少 `threads`；
10. `--service-workers` 非法；
11. `--service-threads` 非法；
12. `docker cp` 失败；
13. 容器内 conf 目录不存在；
14. `docker restart` 失败；
15. 容器重启后未恢复 running；
16. 服务启动超时；
17. 容器重启后无法获取新 root PID；
18. 容器重启后子进程为空；
19. JMX 模板文件不存在；
20. JMX XML 解析失败；
21. JMeter 不存在；
22. JMeter 执行失败；
23. 监控脚本不存在；
24. 监控脚本没有执行权限；
25. 监控脚本输出非数字；
26. `npu-smi` 不存在；
27. 输出目录已存在；
28. 用户参数缺失或非法；
29. `monitor.csv` 不存在；
30. `monitor.csv` 为空；
31. HTML 报告生成失败；
32. PNG 图片生成失败。

### 处理原则

1. 修改 `server_config.json`、`docker cp`、`docker restart`、服务启动检查属于压测前关键步骤；
2. 这些步骤失败时应直接终止压测；
3. 不能在服务配置未生效的情况下继续运行 JMeter；
4. 关键错误直接退出；
5. 监控脚本单次失败不退出，只记录 warning，并将该指标记为 `0`；
6. 压测失败也要保留已有结果目录和日志；
7. `monitor_report.html` 生成失败不能影响已有压测结果保存；
8. PNG 生成失败不能影响 HTML 报告生成；
9. 所有错误信息要清晰；
10. 失败时需要保留已生成的 `run.log` 和 `config.json`，方便排查。

---

## 二十三、README 需求

请生成 `README.md`，内容包括：

1. 项目介绍；
2. 适用环境；
3. 为什么 ARM64 + 华为 310P 环境不能依赖 JMeter 自带监控插件；
4. 为什么要使用脚本化监控；
5. 安装方式；
6. CLI 使用示例；
7. 完整压测示例；
8. 只修改 JMX 示例；
9. 只修改 `server_config.json` 示例；
10. 环境检查示例；
11. 监控脚本说明；
12. `monitor.csv` 字段说明；
13. 监控图表报告说明；
14. `monitor_report.html` 使用说明；
15. PNG 图片可选生成说明；
16. `server_config.json` 格式说明；
17. `workers` 和 `threads` 的含义；
18. `server_name` 如何决定容器内路径；
19. `docker cp` 的目标路径；
20. 为什么修改配置后必须重启容器；
21. 为什么容器重启后必须重新获取 PID；
22. 单进程和多进程指标取值规则；
23. 常见问题；
24. ARM64 + 华为 310P 环境注意事项。

README 中需要包含完整示例命令：

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
  --ready-log-pattern "Booting worker"
```

README 中需要明确完整流程：

```text
修改 server_config.json
        ↓
docker cp 到容器 conf 目录
        ↓
docker restart 容器
        ↓
等待服务启动成功
        ↓
重新获取容器主进程和子进程 PID
        ↓
复制项目内置 JMX 模板到结果目录
        ↓
修改结果目录中的 JMX 副本
        ↓
启动脚本监控
        ↓
启动 JMeter 压测
        ↓
保存 monitor.csv
        ↓
生成 monitor_report.html
        ↓
归档结果目录
```

---

## 二十四、代码质量要求

请保证：

1. 代码可以直接运行；
2. 所有 Python 文件有清晰函数划分；
3. 关键逻辑添加注释；
4. 不要把所有代码都写在一个文件里；
5. Shell 脚本需要有容错处理；
6. Shell 脚本必须只输出一个数字；
7. Python 代码要尽量少依赖第三方包；
8. 支持 Linux 环境运行；
9. 所有路径使用 `pathlib` 处理；
10. `subprocess` 调用要设置 timeout，避免卡死；
11. 日志同时输出到控制台和 `run.log`；
12. 错误要有用户可读的提示；
13. 核心步骤失败时要明确退出码；
14. 尽量使用标准库实现；
15. HTML 报告不依赖外网；
16. HTML 报告不引用 CDN；
17. PNG 生成依赖 `matplotlib`，但必须是可选增强；
18. 没有 `matplotlib` 时不能影响核心流程。

---

## 二十五、最终交付内容

请直接生成完整项目代码，包括：

1. `autoperf/` 目录下所有 Python 源码；
2. `scripts/` 目录下 4 个监控脚本：
   - `run_cpu.sh`
   - `run_mem.sh`
   - `run_npu_usage.sh`
   - `run_npu_mem.sh`
3. `templates/base.jmx` 基础 JMeter 压测模板；
4. `README.md`；
5. `requirements.txt`；
6. `pyproject.toml`；
7. `example_config.json`；
8. 一个示例运行命令；
9. 必要的安装说明。

---

## 二十六、优先保证的核心流程

请优先保证以下核心流程可用：

1. 修改 `server_config.json` 中的 `workers` 和 `threads`；
2. `docker cp` 到容器内：

```bash
/hexapp/ai-<server_name>-serving/conf/server_config.json
```

3. `docker restart` 容器；
4. 等待服务启动完成；
5. 容器重启后重新获取 PID；
6. 复制项目内置 JMX 模板到结果目录，并修改副本中的 `threads` 和 `duration`；
7. 启动监控循环；
8. 调用 4 个监控脚本；
9. 启动 JMeter；
10. 生成 `monitor.csv`；
11. 生成 `monitor_report.html`；
12. 如果 `matplotlib` 可用，生成 PNG 图；
13. 生成 `result.jtl`；
14. 生成 `jmeter.log`；
15. 保存 `config.json`；
16. 保存 `modified_server_config.json`；
17. 保存 `modified.jmx`；
18. 归档结果目录。

---

## 二十七、再次强调

本项目最重要的业务逻辑是：

```text
JMeter 自带监控插件在 ARM64 环境下不可用
        ↓
不能依赖 JMeter PerfMon / ServerAgent 采集指标
        ↓
必须使用自定义脚本采集 CPU、内存、NPU、显存
        ↓
每次采样都通过容器主进程重新查找子进程 PID
        ↓
单进程直接取该进程值
        ↓
多进程对所有指标都取最大值
        ↓
压测前必须先修改 server_config.json 的 workers 和 threads
        ↓
docker cp 到容器 conf 目录
        ↓
docker restart 容器
        ↓
容器重启后重新获取 PID
        ↓
服务启动成功后才能运行 JMeter
        ↓
压测结束后保留 monitor.csv 并生成 monitor_report.html 图表
```
