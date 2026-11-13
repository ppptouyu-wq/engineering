# 智能简历优化与模拟面试平台

《高级软件工程》课程大作业 · CareerLab

CareerLab 面向需要按岗位准备简历和面试的学生。用户可以先诊断简历，再练习岗位面试，最后从历史记录对照每次训练的反馈。

## 本地运行

环境要求为 Python 3.11 或更新版本，以及近期版本的 Chrome、Edge 或 Firefox。首次启动前安装 PDF 解析依赖。

~~~powershell
python -m pip install -r requirements.txt
~~~

在项目目录执行：

~~~powershell
python server.py
~~~

浏览器打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。在终端按 Ctrl+C 停止服务。如果端口被占用，可以运行以下命令并访问对应端口。

~~~powershell
python server.py --port 8080
~~~

首次启动会创建 SQLite 数据库 data/career_lab.sqlite3。重启后可继续查看历史。可通过 --db 指定独立的数据库文件，用于答辩演示或测试。

### 启用 DeepSeek 文字面试

1. 在[DeepSeek 开放平台](https://platform.deepseek.com/)创建有调用权限的 API Key。
2. 在项目目录打开 PowerShell，运行以下命令，按提示粘贴密钥并按回车。如果服务正在运行，先按 Ctrl+C 停止再启动。

   ~~~powershell
   python server.py --save-api-key
   ~~~

   输入会隐藏，密钥保存到本机 .local/deepseek.json。以后直接运行 python server.py 即可自动读取，也可再次用 --save-api-key 更换密钥。该配置文件为明文，已加入 Git 忽略规则，打包分享项目时应排除 .local 目录。

   --configure-ai 仍支持只在本次运行输入密钥。读取优先级为本次输入、DEEPSEEK_API_KEY 环境变量、本机保存的密钥。环境变量方式也支持，但须在设置变量的同一个终端启动服务。

   ~~~powershell
   $env:DEEPSEEK_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host '输入 DeepSeek API Key' -AsSecureString)).Password
   python server.py
   ~~~

3. 进入「模拟面试」，勾选「使用 DeepSeek 生成题目与点评」，选择岗位和题数。逐题填写文字回答后，报告会显示点评、优点和下一次可尝试的改进。

默认使用 https://api.deepseek.com 和 deepseek-flash，以非思考模式生成 JSON。可以通过 DEEPSEEK_MODEL 更换为支持 JSON 输出的 DeepSeek 模型。DEEPSEEK_BASE_URL 可设置为官方地址 https://api.deepseek.com 或 https://api.deepseek.com/v1。[接口文档](https://api-docs.deepseek.com/api/create-chat-completion/) · [结构化输出文档](https://api-docs.deepseek.com/guides/json_mode/)

API Key 由后端读取，启动时输入的密钥仅保留在本次服务进程中。启用 DeepSeek 时，出题请求发送岗位与技能，点评请求发送题目、评分要点和回答。请使用去标识化的练习内容。简历诊断在本机处理。关闭 DeepSeek 选项或未配置密钥时，可直接使用本地文字面试。

## 功能与验收

| 功能 | 操作 | 预期结果 |
| --- | --- | --- |
| 简历诊断 | 选择岗位，填入样例、粘贴正文或导入 UTF-8 文本，提交诊断 | 显示总分、四项维度、关键词覆盖、修改建议和可下载的整理稿 |
| 自定义匹配 | 在岗位描述中输入 Python、Redis、SQL，重新诊断 | 报告按岗位描述提取的关键词匹配，并显示已覆盖与待核对项 |
| 模拟面试 | 选择岗位和 3 或 5 道题，逐题用文字作答 | 显示当前进度，可返回上一题修改，提交后展示总分和逐题复盘 |
| DeepSeek 文字面试 | 配置 DeepSeek API Key 后启用 DeepSeek 并完成练习 | DeepSeek 按岗位生成题目，报告展示逐题点评、优点和改进建议，并标注题目与评分来源 |
| 历史复盘 | 从工作台或历史记录打开报告，按类型筛选 | 可查看已完成的诊断和面试报告，支持单条删除 |
| 输入校验 | 提交过短的正文、过短的回答或无效的岗位参数 | 返回可读的错误信息，历史中不会生成无效报告 |

岗位覆盖后端开发、前端开发、数据分析、产品经理、软件测试、运维与云原生、算法与机器学习、移动端开发、网络与信息安全、嵌入式开发，共十类岗位。每类配有五道本地题。

### PDF 简历与定制练习

简历页支持上传文字型 PDF（最多 5 MB、10 页）和 .txt、.md 文件。PDF 在本机内存中提取，不保存上传的原文件。用户核对正文后提交诊断。扫描件和图片型 PDF 需要先进行 OCR，再导入。

配置 DeepSeek 后，简历页可勾选「使用 DeepSeek 优化简历表达」。后端发送简历正文、目标岗位和招聘描述，生成修改建议与完整优化稿，保留本地维度评分。提示词要求保留原有事实，用户仍需核对生成稿。模型失败时使用本地整理稿并在报告中提示。PDF 提取在本机进行，勾选 AI 优化后，提取的简历正文才会随请求发送到 DeepSeek。

诊断报告中的「用这份简历准备面试」会把最多 4,000 字符的经历填入面试表单。用户可编辑目标岗位描述与个人经历，并选择基础、标准或进阶难度。开启 DeepSeek 后，模型结合岗位要求和个人经历定制题目。未启用或出题失败时，采用所选岗位及难度的本地题目。

报告支持「打印 / 另存为 PDF」，可在浏览器打印窗口选择保存为 PDF，生成文件后自行打印或作为邮件附件。逐题反馈支持收藏到「复习题夹」，相同岗位的同一道题再次收藏时更新原回答和建议，避免重复记录。

### 简历版本与持续训练

简历编辑区可以为当前正文命名并保存版本，诊断报告中的优化稿也可以另存。版本库支持载入编辑、删除和逐行对比。对比时统一采用右侧版本的岗位与招聘描述，重新计算两份简历的规则分，避免岗位变化影响比较。版本保存后可以继续编辑，旧稿保留在本机数据库。

「训练统计」按岗位、评分方式和难度分别统计完成次数、平均分、最近十次成绩和各维度均分。图表中的日期可直接打开相应报告，维度可以加入练习计划。一次训练只会显示单次成绩，多次同组记录后才计算相对首次的变化。

复习题夹支持填写新的复习回答，保存后标为已复习，可按状态筛选或重新标为待复习。原面试回答与复习回答分别保存。再次收藏同一岗位同一道题，会更新原回答并重置复习状态。

「练习计划」支持手动安排内容、岗位和日期，也可以从简历建议或训练统计中添加。任务可以标记完成、恢复待办或删除，过期未完成任务会显示逾期。完成比例同步到训练统计页。

数据库启动时自动创建 resume_versions、tasks 表，并为旧 bookmarks 表添加复习字段，保留原有记录。

### 四人小组分工建议

| 方向 | 可以负责的工作 |
| --- | --- |
| 简历处理 | PDF 提取、输入校验、岗位匹配与整理稿 |
| 模拟面试 | 岗位题库、难度设置、DeepSeek 出题与点评 |
| 页面交互 | 简历与面试表单、打印样式、复习题夹 |
| 数据与测试 | SQLite 持久化、并发提交、接口回归与报告整理 |

以上是分工建议，可按小组成员实际承担的工作填写课程材料。

## 答辩演示

1. 打开工作台，进入「简历优化」，点击「填入样例」，生成报告。
2. 展示岗位匹配得分、待核对关键词和简历整理稿。加入自定义岗位描述后再次诊断，比较关键词的变化。
3. 进入「模拟面试」，选择后端开发和三题练习。开启 DeepSeek 时，根据实时生成的题目作答。使用本地题库时，可用下面的虚构回答完成演示。

   - 项目复盘。负责实现课程选课接口，方案是在候补表记录顺序。用 18 个测试用例验证名额分配和重复报名。
   - 系统设计。并发下先限流，再用事务原子扣减库存保持一致性。通过唯一请求 ID 实现幂等，并压测重复请求。
   - 数据库。先查监控和日志定位慢查询，查看执行计划并验证索引命中。用相同数据压测，对比修复前后 p95 耗时。

4. 打开面试报告，展开逐题反馈。进入「历史记录」筛选面试报告，重启服务后再次查看保存结果。

## 架构与模块

~~~mermaid
flowchart LR
    UI["浏览器工作台<br/>HTML / CSS / JavaScript"]
    HTTP["HTTP API<br/>server.py"]
    Rules["诊断与评分<br/>engine.py"]
    DeepSeek["DeepSeek 文本适配<br/>deepseek.py"]
    Cloud["DeepSeek"]
    Bank["岗位与面试题库<br/>question_bank.py"]
    Storage["记录存取<br/>storage.py"]
    DB[("SQLite")]
    UI -->|"JSON 请求"| HTTP
    HTTP --> Rules
    HTTP --> DeepSeek --> Cloud
    HTTP --> Bank
    Rules --> Bank
    HTTP --> Storage --> DB
~~~

| 路径 | 职责 |
| --- | --- |
| public/ | 工作台、表单交互、报告渲染和响应式布局 |
| server.py | 静态文件服务、接口路由、输入校验和错误响应 |
| engine.py | 岗位关键词提取、简历诊断、整理稿和面试评分 |
| resume_files.py | PDF 文本提取、页数与字符数检查 |
| progress.py | 简历版本逐行对比、同条件训练记录统计 |
| public/features.js | 版本库、训练统计和练习计划页面交互 |
| deepseek.py | DeepSeek 文本 API 请求、出题与点评提示词、结构化结果校验 |
| question_bank.py | 岗位画像、题目和逐题评分要点 |
| storage.py | SQLite 表结构、报告保存和历史查询 |
| tests/test_workflow.py | HTTP 主流程、无效输入和面试并发提交测试 |

### 接口与状态

| 方法与路径 | 输入 | 返回 |
| --- | --- | --- |
| GET /api/roles | 无 | 岗位 ID 和名称 |
| POST /api/resumes | role、resume、可选 description | 记录 ID 和诊断报告 |
| POST /api/resumes/import | application/pdf 二进制文件 | 提取正文与页数 |
| GET /api/interviews/config | 无 | DeepSeek 是否已配置 |
| POST /api/interviews | role、count、可选 use_ai、difficulty、description、context | 练习 ID、题目和出题来源 |
| POST /api/interviews/{id}/finish | 按题目顺序排列的 answers | 总分、维度和逐题反馈 |
| GET /api/history | 无 | 已完成记录摘要 |
| GET /api/records/{id} | 记录 ID | 已完成记录详情 |
| DELETE /api/records/{id} | 记录 ID | 删除结果 |
| GET 或 POST /api/bookmarks | 查看题夹，或提交 role、question、answer、note | 收藏列表或收藏记录 |
| DELETE /api/bookmarks/{id} | 收藏 ID | 移除收藏 |
| PATCH /api/bookmarks/{id} | reviewed、复习完成时的 review_answer | 更新复习状态和新回答 |
| GET 或 POST /api/versions | 查询列表或提交 title、role、resume、description | 简历版本 |
| GET 或 DELETE /api/versions/{id} | 版本 ID | 载入或删除版本 |
| POST /api/versions/compare | before、after 版本 ID | 统一岗位条件下的分数与逐行差异 |
| GET /api/analytics | 无 | 按条件分组的训练趋势与维度 |
| GET 或 POST /api/tasks | 查询或提交 title、role、due_date | 练习计划 |
| PATCH 或 DELETE /api/tasks/{id} | done 状态，或任务 ID | 更新或删除计划 |

SQLite 的 records 表保存记录 ID、类型、岗位、创建时间、输入元数据和报告。启动面试时保存当场题目和评分要点的快照，此时报告为空。答完后用一条带条件的更新写入报告。并发或重复提交同一场练习时，以首个成功写入的报告为准。未完成的面试不会出现在历史列表。

DeepSeek 出题和点评分别调用一次文本接口。出题失败时使用本地题库；点评失败时保留当场题目及作答，使用对应题目的规则生成报告。页面明确标注回退后的来源。网络请求设有 20 秒超时。服务进程内，同一场面试的并发提交共享一份点评结果。

## 评分规则与范围

- **简历诊断**按岗位匹配 40%、结构完整 20%、行动表达 20%、成果量化 20% 加权。岗位匹配按关键词覆盖率计算，结构分统计标准标题，表达和量化分检查行动动词及成果数字。整理稿统一行动条目的格式，保留原文中的经历和数字。
- **DeepSeek 点评**按切题与完整性 35%、准确与合理性 40%、具体与可验证性 25% 为每题评分，总分为各题均分。模型结合题面、评分要点和实际回答给出建议。
- **本地面试评估**按要点覆盖 60%、展开程度 25%、证据表达 15% 为每题评分。要点通过关键词匹配，展开程度按有效文字长度估计，证据表达检查指标或验证方式。
- 当前版本为本机单用户原型，评分用于练习反馈。完成后的整理稿和面试回答以明文保存在本机数据库，未提交的回答只保留在当前页面。

## 测试

~~~powershell
python -m unittest discover -s tests -v
~~~

测试会启动独立的本地 HTTP 服务并使用临时数据库，覆盖简历报告、记录回查与删除、无效输入和同一面试的并发提交。DeepSeek 测试使用模拟 HTTP 响应，覆盖正常出题与点评、格式校验及超时回退，无需真实 API Key。
