# Everything に繋がらないときのチェック手順書

Everysearch から別 PC の Everything に繋がらない（Windows ファイアウォール等で弾かれている）ときに使う、
**接続チェックツール**の使い方です。背景の説明は [lan-wifi-connection.md](lan-wifi-connection.md) を参照。

---

## ツールの場所と、どれが何か

スクリプトはすべて **`tools/everything-http-check/`** にあります（ドキュメントは `doc/`）。

| ファイル | 実行する PC | 何をするか |
|----------|-------------|------------|
| `everything-http-tool.bat` | **サーバー PC**（Everything が動いている PC） | ① この PC の Everything 設定を診断（HTTP 有効か・ポート・ID/パスワード・待受）<br>② Windows ファイアウォールに受信許可ルールを追加（UAC で「はい」） |
| `everything-http-remote-check.bat` | **クライアント PC**（Everysearch を使う PC） | 指定したサーバーの Everything HTTP へ **この PC から届くか** だけを確認（ping / TCP / HTTP 応答 / 認証） |
| `everything-http-tool.ps1` | （直接は実行しない） | 上の 2 つの bat から呼ばれる本体 |
| `*.log` | — | 実行結果のログ。bat と同じフォルダに出力（毎回上書き、Git 管理外） |

覚え方: **「tool」＝サーバー側で直す／「remote-check」＝クライアント側で確かめる**。

> ⚠ 3 ファイルは **同じフォルダに置いたまま** 使ってください。bat は隣の `.ps1` を呼びます。
> 別 PC で使うときはフォルダごと（3 ファイル）コピーします。

---

## 手順（基本の流れ）

```
[1] サーバー PC で everything-http-tool.bat   → 診断＋ファイアウォール許可
[2] クライアント PC で everything-http-remote-check.bat → 届くか確認
[3] ログ末尾の【接続可否】を見て、下の対処表で直す → [1] か [2] をやり直す
```

### 手順 1：サーバー PC（Everything がある PC）で実行

1. `tools/everything-http-check/` フォルダごとサーバー PC にコピー（Dropbox 上ならそのまま）
2. **Everything を動かしているのと同じ Windows ユーザー**で `everything-http-tool.bat` をダブルクリック
   - ポートが 8888 以外なら、コマンドプロンプトで `everything-http-tool.bat 9999` のように指定
3. 診断が流れたあと **UAC（ユーザーアカウント制御）が出たら「はい」**
   → 受信規則「`Everything HTTP 8888`」（TCP / プライベートプロファイル / 許可）が作られる
   - 同名ルールが既にあれば削除して作り直すので、何度実行しても OK
4. 画面とログ `everything-http-tool-<このPCのIP末尾6桁>.log` の最後の行を確認

   - `【接続可否】他PCから接続できる見込みです。接続先 <IP>:<ポート> …` → 手順 2 へ
   - `【接続可否】他PCからは接続できない見込みです。理由: …` → 下の対処表へ

5. ログの `--- Primary (for Everysearch) ---` 欄に、Everysearch に入れるべき
   **Host / Port / Username / Password** が出ているので控える

> ⚠ このログには Everything.ini の **パスワードが平文で出ます**。人に渡す・コミットするときは注意。

### 手順 2：クライアント PC（Everysearch を使う PC）で実行

1. 同じく `tools/everything-http-check/` を開き、`everything-http-remote-check.bat` をダブルクリック
2. 聞かれた順に入力
   - **サーバーIP**：手順 1 で控えたサーバー PC の LAN IP（`127.0.0.1` は不可）
   - **ポート**：空 Enter で 8888
   - **ユーザー名／パスワード**：Everything 側で設定していれば入力（無ければ空 Enter）
   - 引数でも可：`everything-http-remote-check.bat 192.168.1.10 8888 ユーザー名 パスワード`
3. ログ `everything-http-remote-<サーバーIP末尾6桁>.log` の最後の行を確認
   - `【接続可否】このPCから対象サーバーへ接続できる見込みです。` → 手順 4 へ
   - `【接続可否】このPCからは接続できない見込みです。理由: …` → 下の対処表へ

> こちらは相手 PC の設定ファイルやプロセスは**見えません**。「この PC から届くか」だけを判定します。

### 手順 3：結果を見て直す

下の対処表で直し、直した側のツールをもう一度実行します。

### 手順 4：Everysearch に設定

Everysearch の **接続設定** タブにサーバー IP・ポート・ユーザー名／パスワードを入れ、
**接続テスト** → **設定を保存**。

---

## 対処表（ログの「理由:」別）

### サーバー PC 側ツール（everything-http-tool.bat）の理由

| 理由 | 原因 | 対処 |
|------|------|------|
| `HTTP サーバーが無効（http_server_enabled≠1）` | Everything の HTTP サーバーが OFF | Everything → ツール → オプション → **HTTP サーバー** を有効化 |
| `ポート 8888 で待ち受けていない` | Everything が停止中、または HTTP サーバー未起動／別ポート | Everything を起動（常駐）。ポート番号を確認して bat の引数を合わせる |
| `ローカルホストのみ待受（他PC不可）。bindings を空にしてください` | 127.0.0.1 だけで待受 | HTTP サーバー設定の **バインド（bindings）を空** にする |
| `ファイアウォール許可ルールが無い／無効（Private 向け）` | UAC で「いいえ」を押した等 | bat を再実行して UAC で **「はい」** |
| `このPCの LAN IP が分からない` | ネットワーク未接続 | Wi‑Fi／有線の接続を確認 |

### クライアント PC 側ツール（everything-http-remote-check.bat）の理由

| 理由 | 原因 | 対処 |
|------|------|------|
| `ポートまで届かない（FW・HTTP未起動・別LAN・AP分離など）` | サーバー側のファイアウォール、Everything 停止、IP 違い、別ネットワーク | ① サーバー PC で手順 1 をやり直す ② IP を確認（`ipconfig`）③ 同じ LAN/Wi‑Fi か、ゲスト Wi‑Fi（AP 分離）や VPN 接続中でないか |
| `サーバーには届いているが認証が必要（401）…` | Everything にユーザー/パスワードが設定されている | ユーザー名／パスワードを入れて再実行 |
| `認証が合わない（401）。ID/パスワードを確認` | 入力した ID/パスワードの誤り | サーバー側ログの `Primary` 欄の値と照合 |
| `TCPは通るが HTTP 応答がこない` | ポートは開いているが Everything が応答しない（ハング・別アプリがそのポートを使用・セキュリティソフトが通信を検査／遮断） | サーバー PC で Everything を再起動 → 手順 1 の `--- Listening / probe ---` 欄で 8888 を掴んでいるプロセスが Everything.exe か確認 → セキュリティソフトの例外設定を確認 |

### ネットワークプロファイルが「パブリック」の場合

ツールが作るルールは **プライベート** プロファイル向けです。
サーバー側ログの `--- Network profile ---` で `Category=Public` になっていると、ルールがあっても弾かれます。
→ Windows の設定 → ネットワークとインターネット → 接続中のネットワークを **「プライベート ネットワーク」** に変更。

---

## 手動でやる場合（ツールが使えないとき）

ファイアウォール許可だけを入れる（管理者 PowerShell）:

```powershell
New-NetFirewallRule -DisplayName "Everything HTTP 8888" -Direction Inbound -Protocol TCP -LocalPort 8888 -Action Allow -Profile Private
```

クライアントから届くかだけ見る（PowerShell）:

```powershell
Test-NetConnection 192.168.1.10 -Port 8888
```

ブラウザで `http://（サーバーIP）:8888/` が開ければ HTTP まで届いています。

---

## 補足

- ログは bat と同じフォルダに 1 本ずつ（上書き）。フォルダに書き込めないときは `%LOCALAPPDATA%\Everysearch\logs` に出ます（画面の `Log:` 行に実際の場所が表示されます）。
- ログに IP・ユーザー名・パスワードが含まれるため、`*.log` は Git 管理外（`.gitignore`）。
- 検索はできるのに「開く」「ファイルコピー」ができない場合は、ファイアウォールではなく**パスの見え方**の問題です → [lan-wifi-connection.md](lan-wifi-connection.md) の「検索はできるが『開く』…」。
