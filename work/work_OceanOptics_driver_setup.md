# Ocean Optics 配布版のUSBドライバー導入の整理（2026-11-27）

## ログから分かること

0.1.0 / build 3136bb1d のユーザー提供ログでは、SeaBreezeが53個のINFを登録しようとし、
33個が成功、20個が失敗している。USB2000 / USB2000Plus / USB4000 のINFは成功している。
失敗は19個が署名情報なし、FlameNIRの1個がカタログ内のハッシュ不一致であり、
HTTPS通信の証明書検証エラーではない。

INFは機種別・派生機種別（`_XP`付きもある）のドライバーパッケージで、全53個を使用するわけではない。
使用中の実機にSeaBreeze互換のドライバーが割り当てられていれば、他機種用の登録失敗は影響しない。
実際に測定できているという報告と矛盾しない。
ただし、このログだけでは接続機種や実際の割り当て先INFは確定できず、以前から入っていたドライバーを
使っている可能性もある。成功件数を装置の動作確認の代わりにはしない。

## 依存関係

| 要素 | 必要性 |
|---|---|
| Pythonパッケージ `seabreeze` / `cseabreeze` | 装置制御に必要。配布版には同梱済み |
| 実機に対応しSeaBreezeからアクセスできるWindows USBドライバー | 必要。既存環境で認識・測定できるなら追加導入不要 |
| 他機種用のINF、同じ機種の全バリエーション | 全件登録は不要 |
| `seabreeze_os_setup`の毎回実行 | 不要。未認識時の導入用 |

上流のWindowsセットアップはZIP内の`*.inf`すべてをPnPUtilに渡す。
PnPUtilの失敗をログに出しても最後に`sys.exit(0)`するため、戻り値だけで成功を判断できない。
PnPUtilの登録成功も、接続中の実機への割り当てを保証しない。

## 今回の変更

- 配布版ツールは最初に`cseabreeze`で検出し、認識済みならダウンロード・登録を省略する。
- 未認識の場合は既存のSeaBreeze導入処理を利用する。機種限定ダウンロードや独自INFは導入しない。
- 導入処理の戻り値にかかわらず最後に検出し、未検出なら失敗として終了する。
- 認識できた場合も「検出確認」と表示し、スペクトル取得はアプリで確認する。
- ソース版Windowsセットアップも同じPython処理を呼び、判定の重複をなくす。
- UIのツールチップ、オンラインマニュアル、READMEを合わせる。

署名チェックの無効化やカタログの書換えは行わない。対応INF自体が拒否されて未認識の場合は、
機種に合う有効な互換ドライバーを別途確認する必要がある。
複数台の場合、このツールの成功は少なくとも1台を検出したことを示す。使用する各装置の確認は必要。
既存の配布済みexeは変わらず、変更の反映には次回Windowsビルドが必要。

## 根拠

- [python-seabreeze OS setup](https://github.com/ap--/python-seabreeze/blob/main/src/seabreeze/os_setup.py)
- [python-seabreeze OS support](https://github.com/ap--/python-seabreeze/blob/main/os_support/readme.md)
- [Microsoft PnPUtil](https://learn.microsoft.com/en-us/windows-hardware/drivers/devtest/pnputil-command-syntax#add-driver)

このPCの実際の割り当てドライバーをWMIで読み取る操作は権限制限により実行できなかった。
OSのドライバー変更や実機へのアクセスは行わず、セットアップの分岐は偽SeaBreezeによるテストで検証する。

## 検証結果

- Python 3.13.11 / Windowsで追加テスト9件が成功。
- 変更したPythonファイルの`py_compile`、`git diff --check`が成功。
- offscreenで既存テスト全体も実行：567件、22エラー、83スキップ。
  `uvicorn` / `pylablib`不足、UIモジュールのimport/属性エラーがあり、全体成功は確認できていない。
- 配布exeの再ビルドと実機での導入・測定確認は未実施。
