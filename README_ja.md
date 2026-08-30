# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <a href="README.md">English</a> | <b>日本語</b>
</p>

Foam-Agent は、OpenFOAM による CFD の作業を AI エージェントに任せるツールです。OpenFOAM の実行環境とチュートリアルを、お使いのハーネス(Claude Code または Hermes Agent)に MCP サーバーとして組み込みます。チャットでシミュレーションを頼めば、エージェントが条件を利用者とすり合わせ、ケースを作って実行し、失敗すれば自分で直し、結果を独立したセッションに検証させたうえで報告します。推論はハーネス側のモデルが行うため、Foam-Agent自体にAPIキーは要りません。

このリポジトリは [csml-rpi/Foam-Agent](https://github.com/csml-rpi/Foam-Agent) のフォークです。ハーネス経由の利用に一本化し(上流の`direct_api`経路は撤去)、手元のOpenFOAMを実測して参照資料を組み立て、ケースを作った当人とは別のセッションが検証を行います。

## クイックスタート

1. **導入する。**
   ```bash
   git clone https://github.com/jumpcfd/Foam-Agent.git && cd Foam-Agent
   uv tool install --from . foamagent   # visualizeも使うなら '.' の代わりに '.[viz]'
   ```
   `foamagent`は`~/.local/bin`に置かれます(PATHが通っていなければ`uv tool update-shell`)。
2. **OpenFOAMを使えるようにする。** ホスト導入なら`source /opt/openfoam10/etc/bashrc`。無い場合はコンテナーイメージを使います。
   ```bash
   docker pull openfoam/openfoam10-paraview56
   foamagent config set openfoam.runtime docker
   ```
3. **作業用のプロジェクトを作る。**
   ```bash
   mkdir ~/cfd && cd ~/cfd
   foamagent init claude-code   # または: foamagent init hermes-agent
   ```
   Claude Codeの場合、`.mcp.json`(MCPサーバーの設定)と`.claude/skills/openfoam-cfd/SKILL.md`がこのディレクトリに書き出されます。Hermes Agentの場合は、自分のHermesプロファイルには触れず専用の2プロファイルを作ります([Hermes Agentの設定](#hermes-agentの設定)参照)。
4. **チュートリアルのカタログを構築する**(OpenFOAM導入ごとに1回): `foamagent index build`
5. **確認する。** `foamagent doctor`が不備とその直し方を教えます。`--review`を付けると使い捨てケースでレビューコマンド自体も試せます。
6. **ハーネスを起動する。** `~/cfd`で`claude`または`foamhermes`を起動し、`foamagent`がconnectedになっていること、`/openfoam-cfd`が現れることを確認します。
7. **依頼する。** 日本語でも英語でも構いません:「Re=1000のキャビティ流れを計算して」。エージェントは不明点を尋ね、`spec.md`を書き、近いチュートリアルからケースを作り、実行し、失敗すれば自分で直し、結果を検証させてから報告します。

### 成果物の出力先

すべての結果は、依頼の内容から名付けられた1つの**ケースディレクトリ**に集まります。

```
~/cfd/cavity/
├── 0/  constant/  system/          OpenFOAMのケースそのもの
├── Allrun, log.*                   実行コマンドと手順ごとのログ
├── spec.md, review-N.md, report.md 一連の書類(下記「仕組み」の検証を参照)
└── .foamagent/                     実行の管理情報
```

場所を自分で決めたい場合は「ケースは/data/cavityに置いて」のように依頼に含めます。結果は普通のOpenFOAMのケースなので、`paraFoam`やParaViewがそのまま使えます。

## 主な特徴

| 特徴 | 内容 |
|---|---|
| お使いのAIツールの中で動く | `foamagent init claude-code` がMCPの設定とSkillを書き出す、この1コマンドだけで済みます |
| 手元のOpenFOAMに基づく | `foamagent index build` が導入済みのOpenFOAMを実測し、エージェントが読むカタログを書き出します |
| 実行するだけでなく検証する | 別セッションが、作る前に仕様を、完走後に結果を検証し、報告書を書きます(下記「仕組み」参照) |
| 推論を要さない点検 | `validate_case` が辞書の欠落・未導入のソルバー・パッチ名の不一致を実行前に検出します |
| ESI版とFoundation版を判別 | どちらが導入されているかを検出し、辞書名などの違いをエージェントに伝えます |

## 必要なもの

| 項目 | 内容 |
|---|---|
| OpenFOAM | ホスト導入かコンテナーイメージのどちらでも可。Foundation v10で検証済み |
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` — 互換Pythonの取得も兼ねます |
| ハーネス | Claude CodeまたはHermes Agent(下記) |

| ハーネス | Workerとして | レビューコマンドとして |
|---|---|---|
| Claude Code(`npm install -g @anthropic-ai/claude-code`) | 動作確認済み | 動作確認済み — 既定の`claude -p` |
| Hermes Agent(`curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash`) | 動作確認済み — 専用の`foamhermes`プロファイル経由 | 動作確認済み — `foamagent init hermes-agent`が作る専用の`foamhermes-review`プロファイル |

上記以外のMCPクライアント(Codex CLI、Cursor、Clineなど)は対象外で、`foamagent init`は設定しません。Hermesのインストーラは回線が遅いとChromiumの取得でハングすることがありますが、Worker・レビューのどちらにも不要なので中断して構いません。

## Hermes Agentの設定

Hermesにはプロジェクト単位のMCP設定が無く、hooks・pluginsもプロジェクト単位ではなくプロファイル単位で設定します——自分の既定プロファイルに書き込むと、CFDと無関係なHermesセッションでも毎回発火してしまいます。`foamagent init hermes-agent`は代わりに専用の2プロファイルを作り、両方を自動で設定します(手作業のマージは不要)。**`foamhermes`**(worker——MCPサーバー・skill・タスク台帳を表示して`task_done`を促すpluginを持つ)と**`foamhermes-review`**(review——MCPサーバーもskillも持たず、workerからも自分のプロファイルからも隔離)。どちらも既定のプロファイルには触れません。

`foamhermes setup`(と`foamhermes-review setup`)をそれぞれ一度だけ実行し、モデルとAPIキーを設定してください——新規プロファイルは何も持たない状態で始まります。以後、素の`hermes`ではなく`foamhermes chat`(`hermes profile create`がPATHに置くコマンド)でCFDの作業を始めてください。`request_review`は既に`foamhermes-review`を指すよう設定済みです。隔離の仕組みと実機での確認内容は`docs/hermes-profiles-notes.md`を参照してください。

## 仕組み

**MCPツール。** `describe_environment`・`search_tutorials`・`validate_case`・`visualize`は測定と検査のみを行い、実行・編集・ログの読み取りはハーネス自身の道具が担います。`request_review`/`review_status`と`request_report`/`report_status`は下記の検証を非同期に進めます(レビューは数十分かかることがあるためです)。

**検証。** 役は3つです。**Worker**(利用者と話す相手)がCFDの主要工程を担い、**Reviewer**(会話を見ない、新規の非対話セッション)がケースを検査し、**Judge**が往復全体を読んで争点ごとに裁定し報告書を書きます。書類はすべてケースディレクトリに残ります(`spec.md`・`review-N.md`・`response-N.md`・`report.md`)。Reviewerは使い捨てのコンテナーでケースに対して読み取り専用のPythonを実行できるため、指摘の根拠を後から検算できます。レビューコマンドが未設定、または`review.mode: off`の場合は、その旨を書類で明言したうえでケース自体は実行されます。

**Skillと知見。** `SKILL.md`(ツールの使い方)はFoam-Agent本体と一体なので、`init`/`sync`が無条件で上書きします。一方、ケースの分類の仕方や繰り返し起きる失敗といったOpenFOAMの知見は別物で、`~/.config/foamagent/knowledge/`に素のMarkdownとして置かれ、最初の1回だけ既定内容で埋められた後は自動では二度と書き換えられません。自由に編集するか独自の`.md`を足してください。既定内容の更新を取り込む唯一の方法は`foamagent sync`で、上書きする前に確認を挟みます。

**参照用のライブラリー。** `foamagent index build`が`catalog.md`・`by-solver.md`・チュートリアルの`cases/`・各コマンドの`--help`を`~/.cache/foamagent/indexes/`に書き出し、以後すべてのケースで共有されます。

**拡張する。** 別の`SKILL.md`を`.claude/skills/<name>/`(Hermesなら`~/.hermes/profiles/foamhermes/skills/cfd/<name>/`)に置けば、Foam-Agentを介さずハーネス自身が検出します。`paraview.dir`に[paraview_mcp](https://github.com/jumpcfd/paraview_mcp)の複製先を設定すると、Worker・Reviewer・Judgeがテキストから推測する代わりに実際のParaViewを使えます。

## 設定

設定の出所は優先順位順に、環境変数(`FOAMAGENT_*`)、プロジェクトの`foamagent.yaml`、`~/.config/foamagent/config.yaml`、コード内の既定値です。`foamagent config`は対話形式で尋ね、`show`/`set`/`unset`/`edit`/`path`は設定ファイルを直接操作します。

| 設定項目 | 用途 | 既定値 |
|---|---|---|
| `openfoam.runtime` | `native`(ホスト)か`docker`か | `native` |
| `openfoam.image` / `openfoam.bashrc` | `docker`方式で使うイメージとそのbashrcのパス | `openfoam/openfoam10-paraview56` |
| `openfoam.fork` | fork判定の上書き | 実測値 |
| `index.dir` | 構築したインデックスの置き場所 | `~/.cache/foamagent/indexes` |
| `paraview.dir` | paraview_mcpの複製先(上記「拡張する」参照) | 未設定 |
| `review.mode` | `full` / `spec`(仕様レビューのみ) / `off` | `full` |
| `review.command` | レビューを起こすコマンドライン全体(モデル・権限フラグ込み) | `claude -p --model claude-sonnet-5 --dangerously-skip-permissions` |

## トラブルシューティング

まず`foamagent doctor`を実行してください。不備とその直し方を教えます。よくある症状は下記のとおりです。

| 症状 | 対処 |
|---|---|
| `foamagent: command not found` | `~/.local/bin`にPATHが通っていない(`uv tool update-shell`)、または`uv sync`環境なら`uv run foamagent ...` |
| `/mcp`に`foamagent`が現れない | `.mcp.json`のあるディレクトリで起動しているか確認し、初回の信頼プロンプトを許可する |
| `⏸ Pending approval`のまま止まる(非対話) | `.claude/settings.local.json`に`{"enabledMcpjsonServers": ["foamagent"]}`を書く |
| 報告書に「独立した検査は行われていない」と出る | レビューコマンドがPATHに無いか、`review.mode`が`off`になっている |

## コンテナーで動かす

```bash
docker build -f docker/Dockerfile -t foamagent:latest .
docker run -it -e FOAMAGENT_SKIP_UPDATE=1 foamagent:latest
```

起動のたびにGitHubから最新のコードを取得します。`FOAMAGENT_SKIP_UPDATE=1`を付けると、構築時点のコードのまま固定されます。

## 開発

```bash
uv sync
uv run pytest -m "not integration" -q
uv run ruff check .
```

単体テストはAPIの認証情報・ネットワーク・Docker・モデルのいずれも要りません。`scripts/manual/e2e_cavity.sh`は実物のハーネスとOpenFOAMを使うE2E回帰で、手で実行します。`viz`の追加依存が`visualize`用のPyVistaを入れます。

## 謝辞

Skill の設計にあたり、[sim-plugin-openfoam](https://github.com/svd-ai-lab/sim-plugin-openfoam)(Apache-2.0)の OpenFOAM 向け Skill を参考にしました。

## 引用

Foam-Agent を研究で利用される場合は、下記の論文を引用してください。

```bibtex
@article{yue2025foam,
  title={Foam-Agent: Towards Automated Intelligent CFD Workflows},
  author={Yue, Ling and Somasekharan, Nithin and Zhang, Tingwen and Cao, Yadi and Chen, Zhangze and Di, Shimin and Pan, Shaowu},
  journal={arXiv preprint arXiv:2505.04997},
  year={2025}
}

@article{somasekharan2026cfdllmbench,
    title={CFDLLMBench: A Benchmark Suite for Evaluating Large Language Models in Computational Fluid Dynamics},
    author={Somasekharan, Nithin and Yue, Ling and Cao, Yadi and Li, Weichao and Emami, Patrick and Bhargav, Pochinapeddi Sai and Acharya, Anurag and Xie, Xingyu and Pan, Shaowu},
    journal={Journal of Data-centric Machine Learning Research},
    year={2026},
    url={https://openreview.net/forum?id=kTcH1MnkjY},
    note={}
}
```

## コミュニティー

中国語圏の利用者は、ボランティアの WeChat アカウント ZDSJTUCFD を追加することで、フォーク元の WeChat コミュニティーに参加できます。ボランティアがグループへ招待します。
