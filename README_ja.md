# Foam-Agent    <a href="https://arxiv.org/abs/2505.04997"><img src="https://img.shields.io/badge/arXiv-2505.04997-b31b1b.svg" alt="Paper"></a>

<p align="center">
  <a href="README.md">English</a> | <b>日本語</b>
</p>

Foam-Agent は、OpenFOAM による CFD の作業を AI エージェントから行えるツールです。ハーネス(このフォークが対応する Claude Code と Hermes Agent)に対して、OpenFOAM の実行環境とチュートリアルを MCP サーバーとして提供します。利用者はチャットで依頼するだけで、条件の合意、ケースの作成、実行、失敗したときの修正、そして結果のレビューと報告までを進められます。

このリポジトリは [csml-rpi/Foam-Agent](https://github.com/csml-rpi/Foam-Agent) のフォークです。ハーネス経由の利用を唯一の経路とする点、手元の OpenFOAM を実測して参照資料を組み立てる点、そしてケースを作った当人とは別の実行が検証を行う点が、フォーク元との違いです。

## 主な特徴

| 特徴 | 内容 |
|---|---|
| お使いの AI ツールの中で動く | `foamagent install claude-code` が MCP の設定と OpenFOAM の Skill を書き出しますので、設定はこの1コマンドで終わります |
| 手元の OpenFOAM に基づく | `foamagent index build` が導入済みの OpenFOAM を実測し(fork、バージョン、ソルバー一覧、チュートリアル)、エージェントが読むカタログを書き出します |
| 実行するだけでなく検証する | 何かを作る前に仕様を利用者の言葉と照合し、完走した結果を仕様と照合し、読む報告書はそのどちらとも別の実行が書きます。詳細は[検証](#検証)に記します |
| 推論を要しない検査 | `validate_case` が辞書の欠落、未導入のソルバー、パッチ名の不一致を実行前に検出します。ミリ秒で終わる点検で、失敗した実行の数分を節約します |
| ESI 版と Foundation 版の判別 | どちらが導入されているかを実測し、その結果をエージェントへ伝えます。辞書名の違い(`physicalProperties` と `transportProperties` など)はエージェントが吸収します。ESI v2406 では検出とカタログ構築(578ケース)まで確認しており、ソルバーの実行は未検証です |

## 必要なもの

| 項目 | 内容 |
|---|---|
| OpenFOAM | ホストに導入したもの、またはコンテナーイメージのどちらでも構いません。Foundation v10 で検証しています |
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh`。依存関係の管理に使うほか、Python本体の調達にも使います。下の `uv tool install` は互換性のあるPythonを自動で取得するため、システムのPythonがFoam-Agentの要件(3.10以上)を満たしている必要はありません(`pip install`/`venv` で入れる場合は満たしている必要があります) |
| ハーネス | Claude Code(`npm install -g @anthropic-ai/claude-code`)または Hermes Agent(`curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| bash`)。詳細は[ハーネスの対応状況](#ハーネスの対応状況) |

### ハーネスの対応状況

**このフォークが対応するハーネスは Claude Code と Hermes Agent の2つです。**`foamagent install` はこの2つ以外の設定を書き出しません。

**Claude Code** は導入コマンド、レビューまで、いずれも動作を確認しています。

**Hermes Agent** は Worker としてもレビュー(review)としても動作を確認しています。Worker としては、MCP 接続と `openfoam-cfd` Skill を通じて実際のケースを最初から最後まで走らせた実績があります。レビューとしては、`hermes-agent` プロファイル(`review.harness: hermes-agent`)が `foamagent doctor --review` の2項目をすべて実測でクリアしています。`foamagent install hermes-agent` 自体が `review.harness` を `hermes-agent` に設定するため、レビューコマンドとして使うための別手順は要りません。

Hermes Agent 自体のインストールは `curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash` です。**注意:** 同じインストーラの後段で Chromium をダウンロードするステップがあり、`hermes` 自体は既に使える状態であるにもかかわらず、回線が遅い・フィルタされている環境ではそこだけ無期限にハングすることが確認されています。Worker としての Hermes 利用にもレビューにも `browser` ツールセットは要らないので、ハングした場合はそのダウンロードだけ中断して構いません。

## クイックスタート

### 1. Foam-Agent を導入する

```bash
git clone https://github.com/jumpcfd/Foam-Agent.git
cd Foam-Agent
uv tool install --from . foamagent
```

結果の画像を出す `visualize` ツールも使う場合は、最後の行を `uv tool install --from '.[viz]' foamagent` としてください。PyVista を追加で導入します。

`uv tool install` は `foamagent` コマンドを `~/.local/bin` へ置きますので、どのディレクトリからでも実行できます。`~/.local/bin` に PATH が通っていない場合は `uv tool update-shell` を実行してください。

リポジトリの中だけで使う場合は `uv sync` でも構いませんが、この場合コマンドは `.venv/bin` にしか置かれません。以降のコマンドすべてに `uv run` を前置し、リポジトリのディレクトリで実行してください(例: `uv run foamagent install claude-code`)。`foamagent install` はその時点で解決された `foamagent-mcp` のパスをそのままハーネス側の設定(`.mcp.json`、Hermesなら `foamagent-hermes.yaml`)に書き込みます。`uv sync` で入れた場合そのパスは `.venv` の中を指すため、後で `.venv` を消したり移動したりするとハーネスのMCP接続が壊れます。長く使う環境では先に `uv tool install` に切り替えてください。

### 2. OpenFOAM を読み込む

ホストに導入した OpenFOAM を使う場合は、bashrc を読み込みます。

```bash
source /opt/openfoam10/etc/bashrc
echo $WM_PROJECT_DIR      # 例えば /opt/openfoam10 と表示されます
```

ホストに導入していない場合は、OpenFOAM のコンテナーイメージを取得します。ホストへの導入は不要です。

```bash
docker pull openfoam/openfoam10-paraview56
foamagent config set openfoam.runtime docker
```

これらのイメージは数GBあるため、回線が遅いと初回の取得に時間がかかります。

このイメージが既定値ですので、設定するのは `openfoam.runtime` だけで足ります。設定は `~/.config/foamagent/config.yaml` に保存されますので、端末を開き直しても設定し直す必要はありません。別のイメージを使う場合は、イメージ名と、その中の bashrc の位置もあわせて設定してください。動作を確認したイメージを下記に示します。

| イメージ | 検出される OpenFOAM | イメージ内の bashrc |
|---|---|---|
| `openfoam/openfoam10-paraview56` | foundation 10、187コマンド | `/opt/openfoam10/etc/bashrc` |
| `opencfd/openfoam-default:2406` | esi v2406、287コマンド | `/usr/lib/openfoam/openfoam2406/etc/bashrc` |

ESI 版を使う場合の設定を下記に示します。

```bash
docker pull opencfd/openfoam-default:2406
foamagent config set openfoam.runtime docker
foamagent config set openfoam.image opencfd/openfoam-default:2406
foamagent config set openfoam.bashrc /usr/lib/openfoam/openfoam2406/etc/bashrc
```

`foamagent config` を引数なしで実行すると、同じ内容を対話形式で設定できます。現在の設定は `foamagent config show` で確認できます。従来の環境変数(`FOAMAGENT_OPENFOAM_RUNTIME` など)も引き続き使えて、設定ファイルより優先されます。詳細は[設定](#設定)に記します。

### 3. 作業用のディレクトリを作り、ハーネスの設定を書き出す

```bash
mkdir ~/cfd && cd ~/cfd
foamagent install claude-code # Claude Codeの場合
foamagent install hermes-agent # Hermes Agentの場合
```

このディレクトリが、以後エージェントと対話する場所になります。書き出されるファイルは下記の2つです。

| ファイル | 役割 |
|---|---|
| `.mcp.json` | Foam-Agent の MCP サーバーの起動方法 |
| `.claude/skills/openfoam-cfd/SKILL.md` | OpenFOAM をどう扱うかをエージェントへ伝える手順書 |

手順2の時点で環境変数を設定していた場合は、その値だけが `.mcp.json` へ引き継がれます。設定ファイルに書いた場合は引き継がれず、サーバーが起動のたびにファイルを読みます。

どこまで動作を確認しているかは[ハーネスの対応状況](#ハーネスの対応状況)をご覧ください。Hermes Agent の場合、Claude Code にはない手作業が1つ必要です。[Hermes Agent を MCP サーバーに繋ぎ込む](#hermes-agent-を-mcp-サーバーに繋ぎ込む)を参照してください。

### Hermes Agent を MCP サーバーに繋ぎ込む

Claude Code の `.mcp.json` と違い、Hermes にはプロジェクト単位の MCP 設定がなく、グローバルな `~/.hermes/config.yaml` しかありません。そのため `foamagent install hermes-agent` は作業ディレクトリに `foamagent-hermes.yaml` を書き出すところまでしか行わず、これを `~/.hermes/config.yaml` へ手作業で一度だけ組み込む必要があります。

1. Hermes の設定を開きます: `hermes config edit`(または `~/.hermes/config.yaml` を直接編集)
2. トップレベルに `mcp_servers:` キーがまだ無ければ、`foamagent-hermes.yaml` の中身をそのまま貼り付けます
3. すでに `mcp_servers:` キーがある場合(Hermes で他の MCP サーバーを使っている場合など)は、`foamagent-hermes.yaml` の `foamagent:` の項目を、その**既存の** `mcp_servers:` キーの下に子要素として追加してください。`mcp_servers:` をもう1つ貼り付けては**いけません**。YAML は同名のトップレベルキーを2つ書いても統合してくれず、後に書いたほうが黙って勝つため、先に登録されていたサーバーが消えてしまいます

`foamagent-hermes.yaml` の中身は例えばこうなっています(`command` のパスは環境によって変わります):

```yaml
mcp_servers:
  foamagent:
    command: "/home/you/.local/bin/foamagent-mcp"
    args:
      - "--transport"
      - "stdio"
    timeout: 1800
    enabled: true
```

`~/.hermes/config.yaml` に既に `some-other-server` のようなエントリがある場合、組み込んだ後はこうなるはずです ― `foamagent` が `some-other-server` の**兄弟**として、同じ1つの `mcp_servers:` キーの下に入っている状態です。

```yaml
mcp_servers:
  some-other-server:
    command: ...
  foamagent:
    command: "/home/you/.local/bin/foamagent-mcp"
    args:
      - "--transport"
      - "stdio"
    timeout: 1800
    enabled: true
```

うまくいったかは `hermes mcp list` で確認できます。`foamagent` が `enabled` と表示されれば成功です。

### 4. チュートリアルのカタログを構築する

```bash
foamagent index build
```

導入済みの OpenFOAM のチュートリアルを読み取り、エージェントが参照する資料を書き出します。OpenFOAM の導入ごとに1回だけ実行してください。

書き出し先は `~/.cache/foamagent/indexes/<fork>-<バージョン>/` です。リポジトリの外にありますので、`git pull` や再インストールで消えることはありません。

### 5. 設定できたことを確認する

```bash
foamagent doctor
```

ハーネスの中で作業を始めてから判明しがちな不備を、事前に点検します。点検するのは、OpenFOAM に到達できるか、そのインストールに対するカタログが構築済みか、独立したレビューを起こすコマンドが導入されているか、レビューが計算を行えるか、この場所の `.mcp.json` が現在の設定と一致しているかの5点です。設定は変更しません。不備があった項目には、それを直すコマンドが併記されます。

```
  [ok  ] OpenFOAM: foundation 10, 187 applications (docker runtime)
  [ok  ] Reference library: /home/you/.cache/foamagent/indexes/foundation-10
  [ok  ] Review command: /home/you/.local/bin/claude; reviewer on claude-sonnet-5, judge on claude-sonnet-5
  [ok  ] Review sandbox: docker, image python:3.12-slim, 300s per script
  [ok  ] Harness configuration: /home/you/cfd/.mcp.json
```

`--review` を付けると、設定済みのレビューコマンドを実際に起動し、何にも使われない使い捨てのディレクトリに対して、指示に従うか、サンドボックスを使えるかの2点を確かめます。Claude Code 以外のハーネスが `review.command` として実際に使えるかどうかを見る、いちばん早い方法です。実際のレビュー(10分以上)と違って所要は数十秒で済み、フラグの綴りがそのハーネスに合っていない場合は、実際のレビューと同じように失敗します。

```bash
foamagent doctor --review
```

続いて、作業用のディレクトリでハーネスを起動します。

```bash
cd ~/cfd
claude # Claude Codeの場合
hermes # Hermes Agentの場合
```

初回の起動時に、このディレクトリの `.mcp.json` を信頼してよいかを尋ねられますので、許可してください。そのうえで下記の2点を確認します。

1. `/mcp` を実行し、`foamagent` が connected と表示されること
2. スラッシュコマンドの一覧に `/openfoam-cfd` が現れること

`/mcp` に `foamagent` が現れない場合は、[トラブルシューティング](#トラブルシューティング)を参照してください。

非対話(`claude -p`、スクリプト、CI)で起動すると、この信頼の確認プロンプト自体が出ません(答える人がいないため)。その結果 `claude mcp list` が `⏸ Pending approval` のまま止まります。あらかじめ `.mcp.json` の隣に `.claude/settings.local.json` を書いて承認しておいてください。

```json
{ "enabledMcpjsonServers": ["foamagent"] }
```

### 6. 依頼する

あとは普通の日本語または英語で依頼します。

```
Re=1000 のキャビティ流れを計算して
```

エージェントは下記の順に作業します。

1. `describe_environment` で、どの OpenFOAM が使えるか、どのソルバーが実在するかを確認します
2. 依頼で決まっていない点を尋ね、合意した条件を、利用者の依頼文の原文とともに `spec.md` へ書きます
3. `request_review` で、何かを作る前にその仕様の照合を開始し(即座に戻ります)、`review_status` を完了まで問い合わせます
4. `catalog.md` から近いチュートリアルを選び、そのケースのファイルを読みます
5. ケースのファイルを書き、`validate_case` で実行前の検査を行います
6. 自身の道具で `Allrun` を実行し、完了まで見届けます
7. 失敗した場合は自身でログを読み、ファイルを修正して再実行します
8. 完走したら `request_review`/`review_status` で結果をレビューし、`request_report`/`report_status` で利用者が読む報告書を作ります

### 成果物の出力先

実行が生み出すものは、すべて**ケースディレクトリ**の一箇所に集まります。ハーネスを起動したディレクトリの直下に作られ、名前は依頼の内容から付けられます。

```
~/cfd/                                 # ハーネスを起動したディレクトリ
├── .mcp.json
├── .claude/skills/openfoam-cfd/SKILL.md
└── cavity/                            # ← ケースディレクトリ。以下すべてがこの中に入る
    ├── 0/  constant/  system/         OpenFOAM のケースそのもの
    ├── Allrun                         コマンドの並び。エージェント自身が実行する
    ├── log.blockMesh  log.icoFoam     コマンドごとに1つのログ
    ├── 0.5/  1/  …  10/               ソルバーが書いた時刻ディレクトリ。計算結果はここ
    ├── visualization.png  cavity.foam visualize が作る。.foam を ParaView で開く
    ├── spec.md                        合意した条件。依頼文の原文を引用してある
    ├── review-1.md  response-1.md     レビューとそれへの応答。1巡につき1組
    ├── report.md                      最後に利用者が読む報告書
    ├── review-work/                   レビューが数値を出すのに使った Python
    └── .foamagent/                    実行の管理情報。利用者が開く必要はない
```

この場所を決めるのは Foam-Agent ではなくエージェントであり、名前は依頼の内容によって変わります。自分で決めたい場合は依頼にそう書きます(例:「ケースは /data/cavity に置いて」)。

結果は普通の OpenFOAM のケースですから、既存の道具がそのまま使えます。`paraFoam -case ~/cfd/cavity` で開くか、`cavity.foam` を ParaView で開いてください。

ケースディレクトリの外に書かれるのは、手順4で作るチュートリアルのカタログだけです。こちらは `~/.cache/foamagent/indexes/` にあり、すべてのケースで共有されます。

## 仕組み

### MCP ツール

Foam-Agent が公開するツールは下記の8個です。ケースの実行、ログの読み取り、ソルバーの選定、辞書の内容、失敗したときに何を変えるかの判断は、すべてハーネス側のエージェントが自身の道具で行います。最初の4つは測定・検査のみを行い、何も実行しません。最後の4つが例外で、[検証](#検証)に記します。

| ツール | 内容 |
|---|---|
| `describe_environment` | どの OpenFOAM が導入されているか、ソルバーは何があるか、カタログはどこにあるかを返します |
| `search_tutorials` | カタログを語の一致で検索します |
| `validate_case` | 辞書の欠落、未導入のソルバー、メッシュと場のパッチ名の不一致を実行前に検出します |
| `visualize` | PyVista で結果を描画します。決定的なテンプレートのみを使います |
| `request_review` | 仕様、または完走した結果の独立したレビューを開始し、すぐに戻ります |
| `review_status` | レビューの状態を返します。実行中でも即座に戻ります |
| `request_report` | 利用者に示す報告書の作成を開始し、すぐに戻ります |
| `report_status` | 報告書の状態を返します。実行中でも即座に戻ります |

以前はソルバー実行の開始・照会、ログの読み取り、ケースファイルの一覧・読み書き、ログの失敗分類を行うツールもありました。実地では、ハーネス自身の同等機能(`Bash`、`Read`/`Write`、ログを直接読む)の方が使われ、これらは一度も有効に使われていなかったため、すべて撤廃しました。分類ツールに唯一あった本物のドメイン知識(一目で気づくべき失敗の特徴)は、ツール呼び出しなしでエージェントの手元にあるよう、同梱の Skill の中へ移しました。撤廃されたツールが必要な場合は git の履歴を参照してください。

### 検証

あるエージェントが作ったケースを同じエージェントが検査しても、それは「正しいと判断した当人」が検査したにすぎません。そこで検査は別の場所で行います。`request_review` と `request_report` は、利用者が使っているハーネスの非対話セッションを新しく起こします。別プロセスであり、ケースを作った会話は見えません。レビューは数十分かかることがあり、そのあいだ開いたままの MCP ツール呼び出しにはどの MCP クライアントのタイムアウトも耐えられないため、両ツールとも識別子を返してすぐ戻ります。`review_status`/`report_status` を(`wait_seconds` を付けて数分ずつ)state が `done` になるまで問い合わせます。

役は3つです。利用者が対話する相手(**Worker**)が CFD の主要工程を担います。**Reviewer** はケースを読んで、その誤りを探します。**Judge** は往復の全体を読み、争点ごとに裁定して報告書を書きます。足して二で割ることはしません。

Reviewer と Judge は、プロンプトで役割だけを伝えられた、ハーネスの普通の(信頼された)セッションです。ツールを制限してケースから隔離する、という方式ではありません。以前は書き込み系ツールを名指しで禁じ、それを許さないハーネスに対してはケースの使い捨てコピーに向けて動かしていましたが、どちらも実際のツールを壊す頻度のほうが、何かを捕まえる頻度より高かったため、やめました。Claude Code では、Worker 自身の `foamagent` MCP サーバー自体を Reviewer・Judge に一切見せないことが今もはっきり境界として残っています。これは `--strict-mcp-config` によるもので、プロンプト任せではなく機構として保証されます(読み取り専用の `run_script` サンドボックス(後述)と、`paraview.dir` を設定していれば `paraview` サーバーだけは見えます)。もっとも、ケースの実行や編集がハーネス自身の道具に移った今、Worker側のサーバーに残っている「ケースに対して何かする」ツールは`visualize`がPNGを書き込む程度でほぼありません — それでもこの境界を維持するコストはゼロなので、将来ここに別のツールが増えたときのために残しています。Hermes にはこれに相当する呼び出し単位の機構がありません。以前は MCP サーバーを持たない別プロファイルで同等の境界を作っていましたが、その隔離自体が実際のツール呼び出しを壊す頻度のほうが高く([ハーネスの対応状況](#ハーネスの対応状況)参照)撤廃したため、`hermes-agent` では Reviewer・Judge も Worker の `foamagent` サーバーを、他のツールと同じく見ることができます。この境界が必要な場合は、別プロファイルではなく `hermes` プロセス自体を丸ごとコンテナーに隔離してください。

やり取りはすべて書類で行い、書類は[ケースディレクトリ](#成果物の出力先)に残ります。

| ファイル | 書き手 | 内容 |
|---|---|---|
| `spec.md` | Worker | 合意した条件と、利用者の依頼文の原文。照合の相手はこの原文です |
| `review-<n>.md` | Reviewer | 1ラウンド分の指摘 |
| `response-<n>.md` | Worker | 何を直したか、あるいはなぜその指摘は当たらないか |
| `report.md` | Judge | 依頼の要約、実施した計算、結果、争点ごとの裁定、そして計算の限界 |
| `review-work/` | Reviewer、Judge | 数値の算出に用いた Python。書類ごとに1ディレクトリ |

ラウンドの上限は各段階2回で、サーバーが管理します。それ以上続けても議論は収束せず、打ち切りの判断は当事者のどちらにも属さないためです。

Reviewer は計算もできます。残差の推移を目で追い、質量収支を合計せずに「取れている」と書くのは、もっともらしい結果がレビューを通ってしまう典型的な経路です。そこで Reviewer には Python の実行手段を与えています。スクリプトを書くと、Foam-Agent が使い捨てのコンテナーで実行します。ケースは読み取り専用でマウントされ、ネットワークはありません。このマウントによって「ケースは読めるが書き換えられない」がカーネルの性質になります(ツール名の一覧が漏れなく網羅されていることを期待する方式ではなくなります)。スクリプトはケース内に残りますので、指摘の根拠となった計算を Judge も利用者も後から検算できます。Docker が必要です。ない場合もレビューは動き、実行できなかった点検を明記するよう指示されます。

レビューのコマンドが設定されていない環境でも計算自体は動きます。その場合、両ツールは「独立した検査は行われていない」旨の書類を返し、エージェントはそれを利用者へ伝えるよう指示されています。

レビューが用いるプロンプトはパッケージ内の Markdown です。点検の観点を変えるには、同名のファイルを `~/.config/foamagent/templates/` に置いてください。

| テンプレート | 用途 |
|---|---|
| `reviewer-spec.md` | 仕様を依頼文と照合する |
| `reviewer-result.md` | 完走した結果をレビューする |
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

設定の出所は4つあり、下記の順に優先されます。

| 優先順位 | 出所 | 設定する方法 |
|---|---|---|
| 1 | 環境変数 | `export FOAMAGENT_OPENFOAM_RUNTIME=docker` |
| 2 | プロジェクトの設定ファイル。作業ディレクトリーとその上位(`.git` を持つディレクトリーまで)の `foamagent.yaml` | `foamagent config set --project openfoam.image ...` |
| 3 | 利用者の設定ファイル `~/.config/foamagent/config.yaml` | `foamagent config set openfoam.image ...` |
| 4 | コード内の既定値 | — |

```bash
foamagent config                     # 対話形式で質問し、答えを書き出します
foamagent config show                # 全項目の現在値と、4つのうちどこから来た値かを表示します
foamagent config set review.judge.model claude-opus-5
foamagent config unset openfoam.image   # 既定値に戻します
foamagent config edit                # $EDITOR で開きます。コメントは保たれます
foamagent config path                # どのファイルを読んでいるかを表示します
```

環境変数を最上位に置いているのは、既に `.mcp.json` や CI、スクリプトに書かれている値をそのまま動かすためです。裏を返すと、そのシェルに残った古い `export` が、いま編集したファイルより優先されます。`foamagent config show` が各値の出所を表示しますので、食い違いはそこで確認できます。`.mcp.json` に焼き込まれた環境変数が現在の設定と食い違う場合は、`foamagent doctor` が指摘します。

プロジェクトの設定ファイルは、設定を作業の場所に付随させるためのものです。特定の OpenFOAM イメージを要するケース群があるとき、それを起動するシェルではなく、ケースの隣の `foamagent.yaml` に書けます。

### OpenFOAM の実行方式

| 設定項目 | 環境変数 | 用途 | 既定値 |
|---|---|---|---|
| `openfoam.runtime` | `FOAMAGENT_OPENFOAM_RUNTIME` | `native` はホストの導入を読み込み、`docker` はイメージ内で実行します | `native` |
| `openfoam.image` | `FOAMAGENT_OPENFOAM_IMAGE` | `docker` 方式で使うイメージ | `openfoam/openfoam10-paraview56` |
| `openfoam.bashrc` | `FOAMAGENT_OPENFOAM_BASHRC` | そのイメージ内の OpenFOAM の bashrc のパス | `/opt/openfoam10/etc/bashrc` |
| `openfoam.fork` | `FOAMAGENT_OPENFOAM_FORK` | 生成の対象とする fork | 導入されているもの |

`docker` 方式では、ケースディレクトリをコンテナー内の同一の絶対パスへマウントしますので、ログに現れるパスがホスト側と一致します。呼び出し元の UID と GID を渡しますので、生成されたファイルが root 所有になりません。

### インデックスとカタログ

| 設定項目 | 環境変数 | 用途 | 既定値 |
|---|---|---|---|
| `index.dir` | `FOAMAGENT_INDEX_DIR` | 構築したインデックスの置き場所 | `~/.cache/foamagent/indexes` |
| `index.max_file_kb` | `FOAMAGENT_INDEX_MAX_FILE_KB` | この大きさを超えるチュートリアルのファイルは、内容を保存せず記録のみ行います | `100` |

構築済みのインデックスを確認するには `foamagent index list` を実行します。

### シミュレーション結果を見る(paraview_mcp)

| 設定項目 | 環境変数 | 用途 | 既定値 |
|---|---|---|---|
| `paraview.dir` | `FOAMAGENT_PARAVIEW_MCP_DIR` | [paraview_mcp](https://github.com/jumpcfd/paraview_mcp) の複製先 | 未設定 |

`paraview.dir` を設定してから `foamagent install` を実行すると、`.mcp.json` に `foamagent` と並んで `paraview` サーバーが追加され、そのスキルも `.claude/skills/paraview/` にコピーされます。ParaView 自体を導入するのは `foamagent install` の仕事ではないため、この設定は任意です。既に立ち上がった ParaView を、フィールドの数値を読む・スライスを切る・スクリーンショットを撮るといった形で使えるようになり、Reviewer と Judge にも同じサーバーが `--strict-mcp-config` 越しに `run_script` と並べて渡されるので、後処理のテキストから結果を推測するのではなく、Worker と同じやり方で結果を確かめられます。未設定のままなら何も変わりません。

### 検証の設定

こちらに対応する環境変数はありません。引数の並びを持つコマンドは1つの環境変数に収まらないためです。他の項目と同じ設定ファイルに置きます。

```yaml
review:
  harness: claude-code                                     # 下記6項目をまとめた名前
  command: [claude, -p]                                    # 起こすハーネスのセッション
  model: claude-sonnet-5                                   # すべての役が使うモデル
  reviewer:
    model: claude-sonnet-5                                 # ケースを点検するモデル
  judge:
    model:                                                 # 未設定時: 上の review.model を継承(既定では claude-sonnet-5)。点検より強いモデルに裁定させたい場合は claude-opus-5 などに設定
  model_flag: --model                                      # その名前の渡し方
  skip_permissions_flag: --dangerously-skip-permissions    # ツールを全面的に許可する渡し方
  prompt_separator: "--"                                   # オプション解釈の終わり
  timeout_seconds: 1800
  mode: full                                               # full / spec / off
  sandbox:
    runtime: docker            # none にすると計算の手段を与えません
    image: python:3.12-slim    # 初回の使用時に1度だけ取得します
    timeout_seconds: 300       # レビュー全体ではなくスクリプト1本あたり
```

`review.harness` は、この下に並ぶ項目(`command` から `strict_mcp_config_flag` まで)をまとめて選ぶための名前です。手で1項目ずつ書き換える代わりに使います。組み込みのプロファイルは `claude-code`(既定)と `hermes-agent` の2つです。どちらも `foamagent doctor --review` を実際に走らせて確認済みです([ハーネスの対応状況](#ハーネスの対応状況)参照)。知らない名前を指定すると、警告のうえで `claude-code` に戻ります。個別の項目を書けば、`harness: claude-code` を指定したままでもそちらが優先されますので、`harness` と `model_flag` を両方書くといった使い方もできます。別のハーネス用のプロファイルを追加するのは、`foamagent doctor --review` をそのハーネスに対して実際に走らせてからにしてください。試したことのないフラグの綴りは、名前が付いているだけの当て推量です。`hermes-agent` は別手順が要りません。`foamagent install hermes-agent` 自体が `review.harness` を `hermes-agent` に設定します。

レビューと報告書は `model` に書いたモデルで動きます。ハーネス側の既定に委ねずここに書くようにしたのは、自分の結果を何が点検したのかを利用者に推測させないためです。モデル名はコマンドラインに載りますので、レビューを起こしたときにサーバーが出す記録にも、どのモデルで走ったかが残ります。既定は Sonnet です。レビューの仕事はケースを読み、計算し、公表値と突き合わせることだからです。ハーネスが受け付ける名前であれば、ここに何を書いても構いません。`--model` を取らないコマンドを使う場合は `model: ''` としてください。この設定を入れる前と同じく、モデルの選択はハーネス側に委ねられます。

`review.mode` はレビューをどこまで行うかを決めます。既定の `full` は、仕様レビュー、結果レビュー、報告書のすべてを行います。`spec` は最初の1回だけを残します。要求と違う問いに答えているケースを捉える、費用の軽い点検です。`off` はいずれも行いません。無効にした段階は、レビューコマンドがない環境と同じく「実施しなかった」旨の書類を返しますので、点検済みのケースと取り違えることはありません。`full` 以外を選ぶのは、点検が目的ではない作業、例えばベンチマークや、20回目の試行にあたるケースです。ファイルを手で編集する場合は `mode: 'off'` と引用符を付けてください。YAML は裸の `off` を真偽値として読むためです。

`review.model` は全体に効きます。役ごとに分けられるようにしたのは、検証者と裁定者が同じ仕事ではないためです。検証者はケースを読んで計算し、裁定者は両者のやり取りを読んで裁定し、利用者が読む報告書を書きます。`review.reviewer.model` と `review.judge.model` は、その役に限って共通の指定を上書きします。どちらの役がどのモデルで動くかは `foamagent config show` に表示されます。役によって変わるのはモデルだけで、ツールへのアクセスと時間制限は両者で共通です。レビューがケースに対して何をできるかが、依頼した役によって変わってはならないためです。

いずれの項目も上記が既定値ですので、変更したいときだけファイルを置いてください。別のハーネスを指す、あるいは `command` にネットワークを持たないレビューハーネスを指定してウェブへの経路ごと外す、といった用途です。`skip_permissions_flag` は、非対話(`-p`)セッションが何らかのツールを使えるようにするための項目です。これがないと Claude Code は誰も事前承認していないツール呼び出しをすべて拒否します(誰も答えられない確認プロンプトで止まったままにはなりません)。つまりこれがないとレビューはケースを読むことすらできません。渡さずに全面アクセスを許すコマンドでは `''` にしてください。`hermes-agent` のプロファイルは既にそうなっています。Claude Code では、Worker 自身の `foamagent` MCP サーバーは今も Reviewer・Judge から外されています。Foam-Agent 自身の `run_script` サンドボックスと、`paraview.dir` が設定されていれば `paraview` サーバーだけを通し、レビューのセッションは `--strict-mcp-config` つきで起こすためです。Hermes にはこの呼び出し単位の機構がないため、`hermes-agent` では Reviewer・Judge も Worker の `foamagent` サーバーを見ることができます([検証](#検証)参照)。

コンテナーのメモリー・CPU・プロセス数の上限は設定項目にしていません。ファイルで引き上げられる上限は、スクリプトを直す代わりに引き上げられるためです。

### OpenFOAM の fork について

fork(Foundation 版か ESI 版か)とバージョンは実測しますので、通常は設定不要です。`describe_environment` が返す値と、インデックスの格納先の名前(`foundation-10`、`esi-v2406` など)に反映されます。

`openfoam.fork`(または `FOAMAGENT_OPENFOAM_FORK`)を設定した場合は、実測の結果よりもその指定を優先します。ESI 版を導入した環境で Foundation 版の規約に沿った出力を得たい場合など、意図的に食い違わせるときに使ってください。指定と実測が食い違う場合は警告を出力します。

### その他

| 環境変数 | 用途 | 既定値 |
|---|---|---|
| `FOAMAGENT_LOG_LEVEL` | ログの詳細度。ログは標準エラーへ出力し、標準出力には MCP の通信のみを流します | `INFO` |
| `FOAMAGENT_ROOT` | `runs/` を探す位置。上流のパイプラインの名残であり、ケースはここには置かれません([成果物の出力先](#成果物の出力先)を参照) | リポジトリのルート |
| `FOAMAGENT_CONFIG_HOME` | 設定ファイルとテンプレートをまとめて移します | `~/.config/foamagent` |
| `FOAMAGENT_CONFIG_FILE` / `FOAMAGENT_TEMPLATES_DIR` | 片方だけを移します | — |
| `FOAMAGENT_PROJECT_CONFIG` | プロジェクトの設定ファイルを直接指定します。存在しないファイルを指定すると、プロジェクトの設定はないものとして扱います | 上位へ遡って探索 |

上記の4つに設定ファイル側の項目はありません。設定ファイルの位置を決めるための指定だからです。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `foamagent: command not found` | `uv tool install` を使った場合は `~/.local/bin` に PATH が通っているかを確認してください(`uv tool update-shell` で設定できます)。`uv sync` を使った場合は `uv run foamagent ...` の形で実行してください |
| 意図しない `foamagent` が起動する | `which foamagent` で実体を確認してください。conda など別の環境に古い Foam-Agent が入っている場合、そちらが優先されることがあります |
| 何かがうまく動かない | `foamagent doctor` を実行してください。不備の内容と、それを直すコマンドが表示されます |
| `No OpenFOAM environment could be detected` | ホストの OpenFOAM を使う場合は bashrc を読み込み、`echo $WM_PROJECT_DIR` に値が出ることを確認してください。コンテナーを使う場合は `foamagent config show` の `openfoam.runtime` が `docker` であることを確認してください |
| 設定を変えたのに反映されない | `foamagent config show` が各値の出所を表示します。そのシェルに残っている環境変数は設定ファイルより優先されます |
| `/mcp` に `foamagent` が現れない | `.mcp.json` のあるディレクトリで起動しているかを確認してください。起動時の信頼の確認を拒否した場合は、`claude` を再起動して許可してください |
| `claude mcp list` で `foamagent` が `⏸ Pending approval` のまま止まる | 信頼の確認プロンプトに答える人がいなかったためです(`claude -p`、スクリプト、CI)。`.mcp.json` の隣に `.claude/settings.local.json` を作り、`{"enabledMcpjsonServers": ["foamagent"]}` と書いてあらかじめ承認しておいてください |
| `describe_environment` の `library` が空になる | `foamagent index build` をまだ実行していません。OpenFOAM の導入ごとに1回必要です |
| エージェントが存在しないソルバーを使おうとする | `describe_environment` を先に呼ぶよう促してください。Skill には手順として書いてありますが、会話が長くなると省かれることがあります |
| 実行が終わらない | いまはエージェント自身の道具で `Allrun` を実行しているので、止める手段もハーネス側の機能次第です(バックグラウンドのシェルを止める、中断する、など)。Foam-Agent 自体にはこれに関するタイムアウトはありません |
| 可視化が `ImportError`/`ModuleNotFoundError` で失敗する | `viz` の追加依存(PyVista)が必要です。リポジトリのディレクトリで `uv tool install --force --from '.[viz]' foamagent` を実行し、入れ直してください |
| 可視化が負の終了コード(シグナルによる強制終了、-11/SIGSEGVが多い)で失敗する | PyVistaの導入の問題ではありません。VTKがディスプレイを開こうとしてクラッシュしています。コンテナー・CI・X転送なしのSSHなど、ヘッドレス環境でよく起きます。オフスクリーン描画に必要なOSパッケージを導入してください。Debian/Ubuntuの例: `apt-get install -y xvfb libgl1-mesa-glx libxrender1 libxext6 libsm6` |
| 報告書に「独立した検査は行われていない」と出る | レビューのコマンドがこの環境の PATH にありません。ハーネスの CLI を導入するか、`~/.config/foamagent/config.yaml` の `review.command` を手元にあるものへ向けてください |
| レビューに「計算を実行できなかった」と出る | レビューのスクリプトはコンテナーで実行しますので、Docker が必要です。導入するか、実行できなかった点検が明記されたレビューとして受け取ってください |

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

単体テストは、API の認証情報、ネットワーク、Docker、モデルの実行のいずれも必要としません。レビューのセッションを起こすテストは1つもなく、検査するのは「起こすとしたらどのコマンドになるか」「ラウンド上限が守られるか」「ケースにどの書類が残るか」です。この制約が `import foamagent` に副作用を持たせないための担保となっていますので、新しい単体テストもこの範囲に収めてください。実物の OpenFOAM を必要とするテストには `integration` の印を付けており、既定では除外されます。

E2E 回帰は `scripts/manual/e2e_cavity.sh` です。実物のハーネスと実物の OpenFOAM を使いますので、CI ではなく各段階の受け入れ確認時に手で実行します。

CI は push とプルリクエストのたびに、lint、Python 3.10 と 3.12 での単体テスト、およびホイールの構築を実行します。

追加依存の一覧を下記に示します。コアの導入では重い依存を意図的に除いています。

| 追加依存 | 内容 | 必要となる場面 |
|---|---|---|
| `viz` | PyVista | 結果を描画する場合 |
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
