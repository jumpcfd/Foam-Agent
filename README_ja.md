# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <a href="README.md">English</a> | <b>日本語</b>
</p>

Foam-Agent は、OpenFOAM による CFD の作業を AI エージェントから行えるツールです。Claude Code のようなハーネス(AI コーディングツール)に対して、OpenFOAM の実行環境とチュートリアルを MCP サーバーとして提供します。利用者はチャットで依頼するだけで、条件の合意、ケースの作成、実行、失敗したときの修正、そして結果の審査と報告までを進められます。

推論はハーネス側のモデルが行いますので、Foam-Agent に API キーを設定する必要はありません。

このリポジトリは [csml-rpi/Foam-Agent](https://github.com/csml-rpi/Foam-Agent) のフォークです。ハーネス経由の利用を唯一の経路とする点、手元の OpenFOAM を実測して参照資料を組み立てる点、そしてケースを作った当人とは別の実行が検証を行う点が、フォーク元との違いです。プロセス内で推論する経路(`direct_api`)は削除しました。

## 主な特徴

| 特徴 | 内容 |
|---|---|
| お使いの AI ツールの中で動く | `foamagent install claude-code` が MCP の設定と OpenFOAM の Skill を書き出しますので、設定はこの1コマンドで終わります |
| 手元の OpenFOAM に基づく | `foamagent index build` が導入済みの OpenFOAM を実測し(fork、バージョン、ソルバー一覧、チュートリアル)、エージェントが読むカタログを書き出します |
| 実行するだけでなく検証する | 何かを作る前に仕様を利用者の言葉と照合し、完走した結果を仕様と照合し、読む報告書はそのどちらとも別の実行が書きます。詳細は[検証](#検証)に記します |
| 非同期の実行 | ソルバーを起動し、状態を照会し、ログを追い、必要なら停止できます。1時間かかる計算のために接続を1時間保つ必要がありません |
| 推論を要しない検査 | `validate_case` が辞書の欠落、未導入のソルバー、パッチ名の不一致を実行前に検出し、`classify_errors` が失敗したログの意味を示します |
| ESI 版と Foundation 版の判別 | どちらが導入されているかを実測し、その結果をエージェントへ伝えます。辞書名の違い(`physicalProperties` と `transportProperties` など)はエージェントが吸収します。ESI v2406 では検出とカタログ構築(578ケース)まで確認しており、ソルバーの実行は未検証です |

## 必要なもの

| 項目 | 内容 |
|---|---|
| OpenFOAM | ホストに導入したもの、またはコンテナーイメージのどちらでも構いません。Foundation v10 で検証しています |
| [uv](https://docs.astral.sh/uv/) | 依存関係の管理に使います |
| ハーネス | Claude Code、Codex CLI、Cursor、Cline、Kilo Code のいずれか |

## クイックスタート

### 1. Foam-Agent を導入する

```bash
git clone https://github.com/jumpcfd/Foam-Agent.git
cd Foam-Agent
uv tool install --from . foamagent
```

結果の画像を出す `visualize` ツールも使う場合は、最後の行を `uv tool install --from '.[viz]' foamagent` としてください。PyVista を追加で導入します。

`uv tool install` は `foamagent` コマンドを `~/.local/bin` へ置きますので、どのディレクトリからでも実行できます。`~/.local/bin` に PATH が通っていない場合は `uv tool update-shell` を実行してください。

リポジトリの中だけで使う場合は `uv sync` でも構いませんが、この場合コマンドは `.venv/bin` にしか置かれません。以降のコマンドすべてに `uv run` を前置し、リポジトリのディレクトリで実行してください(例: `uv run foamagent install claude-code`)。

### 2. OpenFOAM を読み込む

ホストに導入した OpenFOAM を使う場合は、bashrc を読み込みます。

```bash
source /opt/openfoam10/etc/bashrc
echo $WM_PROJECT_DIR      # 例えば /opt/openfoam10 と表示されます
```

ホストに導入していない場合は、OpenFOAM のコンテナーイメージを取得します。ホストへの導入は不要です。

```bash
docker pull openfoam/openfoam10-paraview56
export FOAMAGENT_OPENFOAM_RUNTIME=docker
```

このイメージが既定値ですので、設定するのは `FOAMAGENT_OPENFOAM_RUNTIME` だけで足ります。別のイメージを使う場合は、イメージ名と、その中の bashrc の位置もあわせて設定してください。動作を確認したイメージを下記に示します。

| イメージ | 検出される OpenFOAM | イメージ内の bashrc |
|---|---|---|
| `openfoam/openfoam10-paraview56` | foundation 10、187コマンド | `/opt/openfoam10/etc/bashrc` |
| `opencfd/openfoam-default:2406` | esi v2406、287コマンド | `/usr/lib/openfoam/openfoam2406/etc/bashrc` |

ESI 版を使う場合の設定を下記に示します。

```bash
docker pull opencfd/openfoam-default:2406
export FOAMAGENT_OPENFOAM_RUNTIME=docker
export FOAMAGENT_OPENFOAM_IMAGE=opencfd/openfoam-default:2406
export FOAMAGENT_OPENFOAM_BASHRC=/usr/lib/openfoam/openfoam2406/etc/bashrc
```

`export` の効果はそのシェルを閉じるまでですので、手順3と手順4は同じシェルで続けて実行してください。端末を開き直した場合は `export` からやり直します。毎回設定する手間を省くには、`~/.bashrc` に書いておく方法もあります。

### 3. 作業用のディレクトリを作り、ハーネスの設定を書き出す

```bash
mkdir ~/cfd && cd ~/cfd
foamagent install claude-code
```

このディレクトリが、以後エージェントと対話する場所になります。書き出されるファイルは下記の2つです。

| ファイル | 役割 |
|---|---|
| `.mcp.json` | Foam-Agent の MCP サーバーの起動方法 |
| `.claude/skills/openfoam-cfd/SKILL.md` | OpenFOAM をどう扱うかをエージェントへ伝える手順書 |

API キーは書き込まれません。手順2で設定した OpenFOAM 関連の環境変数だけが `.mcp.json` へ引き継がれます。

Claude Code 以外のハーネスは `claude-code` の位置を `codex-cli`、`cursor`、`cline`、`kilo-code`、`generic` に置き換えてください。Claude Code 以外では設定ファイルの取り込み方が異なりますので、コマンドが表示する案内に従ってください。

### 4. チュートリアルのカタログを構築する

```bash
foamagent index build
```

導入済みの OpenFOAM のチュートリアルを読み取り、エージェントが参照する資料を書き出します。OpenFOAM の導入ごとに1回だけ実行してください。所要時間は、Foundation v10 の248ケースで6秒、ESI v2406 の578ケースで13秒でした。

書き出し先は `~/.cache/foamagent/indexes/<fork>-<バージョン>/` です。リポジトリの外にありますので、`git pull` や再インストールで消えることはありません。

### 5. 設定できたことを確認する

作業用のディレクトリで Claude Code を起動します。

```bash
cd ~/cfd
claude
```

初回の起動時に、このディレクトリの `.mcp.json` を信頼してよいかを尋ねられますので、許可してください。そのうえで下記の2点を確認します。

1. `/mcp` を実行し、`foamagent` が connected と表示されること
2. スラッシュコマンドの一覧に `/openfoam-cfd` が現れること

`/mcp` に `foamagent` が現れない場合は、[トラブルシューティング](#トラブルシューティング)を参照してください。

### 6. 依頼する

あとは普通の日本語または英語で依頼します。

```
Re=1000 のキャビティ流れを計算して
```

エージェントは下記の順に作業します。

1. `describe_environment` で、どの OpenFOAM が使えるか、どのソルバーが実在するかを確認します
2. 依頼で決まっていない点を尋ね、合意した条件を、利用者の依頼文の原文とともに `spec.md` へ書きます
3. `request_review` で、何かを作る前にその仕様を依頼文と照合します
4. `catalog.md` から近いチュートリアルを選び、そのケースのファイルを読みます
5. ケースのファイルを書き、`validate_case` で実行前の検査を行います
6. `run_start` で実行し、`run_status` と `run_tail_log` で経過を追います
7. 失敗した場合は `classify_errors` で原因を分類し、ファイルを修正して再実行します
8. 完走したら `request_review` で結果を審査し、`request_report` で利用者が読む報告書を作ります

## 仕組み

### MCP ツール

Foam-Agent が公開するツールは下記の14個です。ソルバーの選定、辞書の内容、失敗したときに何を変えるかの判断は、すべてハーネス側のエージェントが行います。上の12個は測定・実行・検査のみを行い、モデルを呼びません。最後の2つが例外で、[検証](#検証)に記します。

| ツール | 内容 |
|---|---|
| `describe_environment` | どの OpenFOAM が導入されているか、ソルバーは何があるか、カタログはどこにあるかを返します |
| `search_tutorials` | カタログを語の一致で検索します |
| `list_case` | ケースのファイルを一覧します |
| `read_case` | ケースのファイルを1つ読みます |
| `write_case` | ケースのファイルを1つ書きます。`Allrun` には実行権限を付けます |
| `validate_case` | 辞書の欠落、未導入のソルバー、メッシュと場のパッチ名の不一致を実行前に検出します |
| `run_start` | `Allrun` を起動し、すぐに戻ります |
| `run_status` | 実行の状態を返します。実行中でも即座に戻ります |
| `run_tail_log` | ログの末尾を返します |
| `run_stop` | 実行を停止します。コンテナーの場合はコンテナーごと停止します |
| `classify_errors` | ログの失敗を分類し、該当する行と意味を返します |
| `visualize` | PyVista で結果を描画します。決定的なテンプレートのみを使います |
| `request_review` | 仕様、または完走した結果を、独立した実行に審査させます |
| `request_report` | 利用者に示す報告書を作ります |

`read_case` と `write_case` はケースディレクトリの外を拒否します。

### 検証

あるエージェントが作ったケースを同じエージェントが検査しても、それは「正しいと判断した当人」が検査したにすぎません。そこで検査は別の場所で行います。`request_review` と `request_report` は、利用者が使っているハーネスの非対話セッションを新しく起こします。別プロセスであり、ケースを作った会話は見えず、ツールは読み取り系に限られます。ケースのファイルを開き、ウェブを検索することはできますが、何かを書き換えることはできません。

役は3つです。利用者が対話する相手(**Worker**)が CFD の主要工程を担います。**Reviewer** は書類だけを見て、その誤りを探します。**Judge** は往復の全体を読み、争点ごとに裁定して報告書を書きます。足して二で割ることはしません。

やり取りはすべて書類で行い、書類はケースディレクトリに残ります。

| ファイル | 書き手 | 内容 |
|---|---|---|
| `spec.md` | Worker | 合意した条件と、利用者の依頼文の原文。照合の相手はこの原文です |
| `review-<n>.md` | Reviewer | 1ラウンド分の指摘 |
| `response-<n>.md` | Worker | 何を直したか、あるいはなぜその指摘は当たらないか |
| `report.md` | Judge | 依頼の要約、実施した計算、結果、争点ごとの裁定、そして計算の限界 |

ラウンドの上限は各段階2回で、サーバーが管理します。それ以上続けても議論は収束せず、打ち切りの判断は当事者のどちらにも属さないためです。

知っておくとよい点が2つあります。審査の費用は、追加のセッション分としてハーネスの契約に対して発生します(Foam-Agent の API キーではありません)。また、審査のコマンドが設定されていない環境でも計算自体は動きます。その場合、両ツールは「独立した検査は行われていない」旨の書類を返し、エージェントはそれを利用者へ伝えるよう指示されています。

審査が用いるプロンプトはパッケージ内の Markdown です。点検の観点を変えるには、同名のファイルを `~/.config/foamagent/templates/` に置いてください。

| テンプレート | 用途 |
|---|---|
| `reviewer-spec.md` | 仕様を依頼文と照合する |
| `reviewer-result.md` | 完走した結果を審査する |
| `judge-report.md` | 報告書を書く |

### 参照用のライブラリー

`foamagent index build` が書き出す資料を下記に示します。エージェントはこれらを直接読みますので、意味的検索を挟みません。

| 生成物 | 内容 | 規模(Foundation v10) |
|---|---|---|
| `catalog.md` | 全チュートリアルの索引。ケース名、ソルバー、分野、分類、格納先、除外したファイル | 248ケース分の行、約34kB |
| `by-solver.md` | 同じ内容をソルバー別に並べ替えたもの | 約25kB |
| `cases/` | 各チュートリアルのファイル | 4706ファイル、6.8MB |
| `commands/` | 各コマンドの `-help` の出力 | 187ファイル |

`cases/` には形状データ、メッシュのデータ、バイナリ、および100kB を超えるファイルを含めません。Foundation v10 では100ファイル、74.4MB を除外しています。何を除外したかは `catalog.md` の各行に記載しますので、エージェントは元のチュートリアルを見に行くべきかどうかを判断できます。

## 設定

設定項目は `src/foamagent/config.py` にあり、いずれも環境変数で上書きできます。

### OpenFOAM の実行方式

| 環境変数 | 用途 | 既定値 |
|---|---|---|
| `FOAMAGENT_OPENFOAM_RUNTIME` | `native` はホストの導入を読み込み、`docker` はイメージ内で実行します | `native` |
| `FOAMAGENT_OPENFOAM_IMAGE` | `docker` 方式で使うイメージ | `openfoam/openfoam10-paraview56` |
| `FOAMAGENT_OPENFOAM_BASHRC` | そのイメージ内の OpenFOAM の bashrc のパス | `/opt/openfoam10/etc/bashrc` |

`docker` 方式では、ケースディレクトリをコンテナー内の同一の絶対パスへマウントしますので、ログに現れるパスがホスト側と一致します。呼び出し元の UID と GID を渡しますので、生成されたファイルが root 所有になりません。

### インデックスとカタログ

| 環境変数 | 用途 | 既定値 |
|---|---|---|
| `FOAMAGENT_INDEX_DIR` | 構築したインデックスの置き場所 | `~/.cache/foamagent/indexes` |
| `FOAMAGENT_INDEX_MAX_FILE_KB` | この大きさを超えるチュートリアルのファイルは、内容を保存せず記録のみ行います | `100` |

構築済みのインデックスを確認するには `foamagent index list` を実行します。

### 検証の設定

こちらは環境変数ではありません。引数の並びを持つコマンドは1つの環境変数に収まらないため、`~/.config/foamagent/config.yaml` に置きます。

```yaml
review:
  command: [claude, -p]                                    # 起こすハーネスのセッション
  allowed_tools: [Read, Grep, Glob, WebSearch, WebFetch]   # 読み取り系とウェブのみ
  allow_tools_flag: --allowed-tools                        # その一覧の渡し方
  prompt_separator: "--"                                   # オプション解釈の終わり
  timeout_seconds: 900
```

いずれの項目も上記が既定値ですので、変更したいときだけファイルを置いてください。別のハーネスを指す、ウェブ検索を外す、といった用途です。ケースを書き換えうるツール(`Bash`、`Write`、`Edit` など)は、ファイルの記載にかかわらず警告とともに除外します。書き換えられる検証者は検証者ではないためです。

置き場所は `FOAMAGENT_CONFIG_HOME` でまとめて移せます(設定とテンプレートの両方)。個別に移す場合は `FOAMAGENT_CONFIG_FILE` と `FOAMAGENT_TEMPLATES_DIR` を使います。

### OpenFOAM の fork について

fork(Foundation 版か ESI 版か)とバージョンは実測しますので、通常は設定不要です。`describe_environment` が返す値と、インデックスの格納先の名前(`foundation-10`、`esi-v2406` など)に反映されます。

`FOAMAGENT_OPENFOAM_FORK` を設定した場合は、実測の結果よりもその指定を優先します。ESI 版を導入した環境で Foundation 版の規約に沿った出力を得たい場合など、意図的に食い違わせるときに使ってください。指定と実測が食い違う場合は警告を出力します。

### その他

| 環境変数 | 用途 | 既定値 |
|---|---|---|
| `FOAMAGENT_LOG_LEVEL` | ログの詳細度。ログは標準エラーへ出力し、標準出力には MCP の通信のみを流します | `INFO` |
| `FOAMAGENT_ROOT` | `runs/` を探す位置 | リポジトリのルート |

ソルバーの実行を打ち切るまでの秒数は環境変数ではなく、`run_start` の `timeout` で指定します(既定は3600秒)。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `foamagent: command not found` | `uv tool install` を使った場合は `~/.local/bin` に PATH が通っているかを確認してください(`uv tool update-shell` で設定できます)。`uv sync` を使った場合は `uv run foamagent ...` の形で実行してください |
| 意図しない `foamagent` が起動する | `which foamagent` で実体を確認してください。conda など別の環境に古い Foam-Agent が入っている場合、そちらが優先されることがあります |
| `No OpenFOAM environment could be detected` | ホストの OpenFOAM を使う場合は bashrc を読み込み、`echo $WM_PROJECT_DIR` に値が出ることを確認してください。コンテナーを使う場合は `echo $FOAMAGENT_OPENFOAM_RUNTIME` に `docker` が出ることを確認してください。端末を開き直すと手順2の `export` は消えています |
| `/mcp` に `foamagent` が現れない | `.mcp.json` のあるディレクトリで起動しているかを確認してください。起動時の信頼の確認を拒否した場合は、`claude` を再起動して許可してください |
| `describe_environment` の `library` が空になる | `foamagent index build` をまだ実行していません。OpenFOAM の導入ごとに1回必要です |
| エージェントが存在しないソルバーを使おうとする | `describe_environment` を先に呼ぶよう促してください。Skill には手順として書いてありますが、会話が長くなると省かれることがあります |
| 実行が終わらない | `run_status` で状態を確認し、`run_stop` で停止できます。`run_start` の `timeout`(既定は3600秒)に達した実行は自動的に打ち切られます |
| 可視化が失敗する | `viz` の追加依存(PyVista)が必要です。リポジトリのディレクトリで `uv tool install --force --from '.[viz]' foamagent` を実行し、入れ直してください |
| 報告書に「独立した検査は行われていない」と出る | 審査のコマンドがこの環境の PATH にありません。ハーネスの CLI を導入するか、`~/.config/foamagent/config.yaml` の `review.command` を手元にあるものへ向けてください |

## コンテナーで動かす


フォーク元が公開しているイメージがあり、OpenFOAM v10、Python、依存関係一式を含みます。

```bash
docker run -it --name foamagent leoyue123/foamagent
```

このイメージはフォーク元が構築したものであり、このフォークの変更を含みません。このフォークをコンテナーで動かす場合は、ソースからイメージを構築してください。

```bash
docker build -f docker/Dockerfile -t foamagent:latest .
docker run -it -e FOAMAGENT_SKIP_UPDATE=1 foamagent:latest
```

コンテナーは起動のたびに GitHub から最新のコードを取得し、イメージに入っているコードを上書きします。構築した時点のコードで動かす場合は、上記のように `FOAMAGENT_SKIP_UPDATE=1` を設定してください。取得元は `FOAMAGENT_REPO` で変更できます。

MCP サーバーを HTTP で公開する場合は、ポートを開いたうえでサーバーを起動します。

```bash
docker run -it -p 7860:7860 foamagent:latest \
  foamagent-mcp --transport http --host 0.0.0.0 --port 7860
```

接続先の設定を下記に示します。

```json
{
  "mcpServers": {
    "foamagent": {
      "url": "http://localhost:7860/mcp"
    }
  }
}
```

## 開発

```bash
uv sync                          # コアと開発用ツール
uv run pytest -m "not integration" -q
uv run ruff check .
```

単体テストは、API の認証情報、ネットワーク、Docker、モデルの実行のいずれも必要としません。審査のセッションを起こすテストは1つもなく、検査するのは「起こすとしたらどのコマンドになるか」「ラウンド上限が守られるか」「ケースにどの書類が残るか」です。この制約が `import foamagent` に副作用を持たせないための担保となっていますので、新しい単体テストもこの範囲に収めてください。実物の OpenFOAM を必要とするテストには `integration` の印を付けており、既定では除外されます。

E2E 回帰は `scripts/manual/e2e_cavity.sh` です。実物のハーネスと実物の OpenFOAM を使いますので、CI ではなく各段階の受け入れ確認時に手で実行します。

CI は push とプルリクエストのたびに、lint、Python 3.10 と 3.12 での単体テスト、およびホイールの構築を実行します。

追加依存の一覧を下記に示します。コアの導入では重い依存を意図的に除いています。

| 追加依存 | 内容 | 必要となる場面 |
|---|---|---|
| `viz` | PyVista | 結果を描画する場合 |
| `web` | FastAPI、uvicorn | `app.py` のウェブ UI を使う場合 |
| `all` | 上記のすべて | |

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
