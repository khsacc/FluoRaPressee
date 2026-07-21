# Princeton Instruments シャッター制御 詳細仕様・実装計画

## 0. 目的

カメラと同期してシャッター制御が可能なハードウェアに接続された場合に、シャッター制御をアプリに組み込む。

対象: Princeton Instruments PICam カメラのみ（初期対象実機: ProEM:1600(2)）

状態: 設計完了、実装前。属性名・候補値・実際の外付けシャッター接続状態は実機確認待ち。

## 1. 結論

1. **同期シャッターの有無・自動ダークの可否は、かなりの範囲まで自動判定できる。**
   ただし「シャッター関連属性が存在する」「Shutter Type が Vincent CS25 である」だけでは、
   実物のシャッターが接続されている証拠にならない。PICam公式仕様でも Shutter Type は
   「駆動可能な種類」であって存在を示さず、存在確認には Shutter Status を使うとされている。
   したがって、`Active Shutter`、対応する Internal/External `Shutter Status`、
   `Shutter Timing Mode`の書込み可否・候補値を組み合わせて判定する。

2. **初回の正常接続時に判定結果を`spectrometerConfig.json`へ保存し、以降の接続では期待値と
   実機を照合する仕様を採用する。** シャッターがない機種も`expected: "None"`として明示的に
   保存する。設定上はExternalなのに`External Shutter Status != Connected`、あるいは設定した
   型と実機報告が異なる場合は、取得を始めず構成エラーとする。これにより「昨日までは自動darkが
   取れていたが、今日はケーブルが抜けたまま明画像をdarkとして保存した」という失敗を防げる。

3. **自動判定と自動動作は分ける。** 接続時には能力・接続状態を読むだけで、シャッターを試験開閉
   しない。確実に`Connected`と判定できた場合だけ自動darkを有効にする。状態属性がないなど判定が
   曖昧な場合は`expected: "Unresolved"`として記録し、通常測定は許可するが自動darkは無効にする。

4. **dark取得はイベント駆動の状態機械として実装する。** `Always Closed`の設定完了・実値読戻しを
   待ってから露光を開始し、取得成功・取得失敗・ユーザー中止の全経路で元モードへ戻す。現行の
   `on_acq_bg_clicked()`は設定直後に`start_measuring()`を呼ぶため、そのまま前後にsetを追加するだけ
   では競合し、閉じる前のフレームをdarkとして採用する危険がある。

5. **通常測定の推奨モードは設定値として`Always Open`とするが、接続直後には勝手に適用しない。**
   最初の通常取得開始前、またはユーザーがUIでApplyした時に適用する。同じモードなら再設定を省略し、
   Vincent系メカシャッターの不要な開閉を避ける。dark時だけ`Always Closed`へ切り替え、終了後は
   dark直前の実モードへ戻す。

6. **ProEM:1600(2)については前提を訂正する必要がある。** ProEM公式マニュアルでは、512B/BK・
   1024BはフレームトランスファーCCDだが、1600(2)/1600(4)はフルフレームCCDである。また
   ProEM:1600本体に記載される内蔵シャッターはノブで開閉する手動シャッターである。したがって、
   手元の1600²で自動制御できるとすれば、別途ケーブル接続された外付けシャッターと考えるべきで、
   `External Shutter Status=Connected`および`Active Shutter=External`の実機確認を必須とする。
   `Always Open`で通常測定してよいかも、フレームトランスファーを根拠にはせず、実際のスペクトルで
   読出し中入射によるスミア・背景上昇が許容できることを確認して確定する。

## 2. 調査根拠

- [pylablib: Princeton Instruments Picam cameras](https://pylablib.readthedocs.io/en/latest/devices/Picam.html)
  は、専用シャッターAPIではなく`get_attribute_value()`/`set_attribute_value()`と属性オブジェクトで
  PICamパラメータを扱えること、機種ごとに属性・制約が大きく異なるため実機の属性ツリーを調べる
  必要があることを明記している。
- [PICam 5.x Programmer's Manual](https://www.princetoninstruments.com/wp-content/uploads/2022/02/PICAM-5.x-Programmers-Manual-Issue-8-4411-0161-3.pdf)
  によると、`PicamActiveShutter`はNone/Internal/External、`PicamShutterStatus`は
  Connected/Not Connected/Overheated、`PicamShutterTimingMode`はNormal/Always Closed/
  Always Open/Open Before Triggerである。Always Closed/Always Openは非取得中にも有効である。
- 同PICamマニュアルでは、`Shutter Delay Resolution`は**マイクロ秒単位の分解能値**であり、Opening/
  Closing Delayの単位はこの値に依存する。例えばResolution=1000ならDelayの1単位が1 msである。
  したがって、Opening/Closing DelayのPICam生値を無条件にmsとしてUI表示してはならない。
- [ProEM System Manual](https://www.princetoninstruments.com/wp-content/uploads/2020/04/ProEM-System-Manual-Issue-3-4411-0126.pdf)
  は、ProEM:1600(2)/(4)をフルフレームCCDとし、ProEM:1600の本体シャッターを手動ノブ式と記載する。

## 3. 現行コードの状況

### 3.1 そのまま利用できるもの

- `src/camera_princeton.py`
  - `_query_attribute_capability(name)`は`exists`/`relevant`/`writable`/Collection候補/
    Range制約/現在値を取得済み。
  - `_apply_attribute_value(name, value, ...)`はset、commit、属性再取得、実値読戻し、失敗時rollbackを
    実装済み。
  - `_hw_lock`によりsnapと設定変更を排他できる。
  - `_report_orientation_capability()`という接続時調査ログの先例がある。
  - Camera Statusダイアログ用`_STATUS_FIELDS`にはTiming Mode、Opening/Closing Delay、Internal/
    External Type/Statusが既に含まれている。
- `src/ui_mixins/acquisition_mixin.py`
  - 単発・連続・積算の取得完了箇所は`on_data_ready()`/`_process_completed_data()`へ集約されている。
  - `_acquisition_gate`でGUI/API/Sequential間の取得権を排他している。
- `src/file_io.py`
  - スペクトルヘッダーとbackground JSONを一箇所で生成しているため、シャッターメタデータ追加先に
    適している。

### 3.2 変更が必要なもの

- Camera Statusには`Active Shutter`と`Shutter Delay Resolution`がなく、Delayも生値をそのまま
  「ms」と表示している。Resolutionを使った換算が必要。
- カメラスレッドにはシャッター設定要求・完了シグナルがない。
- `on_acq_bg_clicked()`はシャッターを手動で閉じた前提で即座に取得を始める。
- background取得完了時、`stop_measurement()`が取得ゲートを先に解放するため、非同期のモード復帰を
  追加する場合は、復帰完了まで別の取得が割り込まないよう整理が必要。
- `_reopen_camera_connection()`は露光、ADC/EM Gain、温度、ROIを復元するがシャッター設定を復元しない。
- 保存処理は保存時点のUI値からmetadataを組み立てる。dark後にはモードが元へ戻っているため、
  「取得時のシャッターモード」を別途スナップショットして保存しなければならない。

## 4. 対象範囲

### 4.1 今回実装する

- Princeton Instruments PICamカメラのシャッター能力・接続状態の調査と判定
- 初回判定結果の`spectrometerConfig.json`保存、以後の起動時照合
- Active Shutterの期待値設定（None/Internal/External）
- Shutter Timing ModeのNormal/Always Open/Always Closed制御
- Opening/Closing Delayのms表示・動的Range・設定・読戻し
- 自動dark取得（閉じる→取得→元へ戻す）
- 通常測定・backgroundファイルへの取得時シャッターメタデータ保存
- `--debug`用モック能力・値
- PICam接続復旧後のシャッター構成再検証・設定復元

### 4.2 今回は実装しない

- Andorバックエンドのシャッター制御
- `Open Before Trigger`のUI選択（能力ログとCamera Statusには表示する）
- 外部トリガー入力・LOGIC OUT・レーザーとの同期制御
- APIからの新規dark取得エンドポイント
- シャッター寿命カウンタ、最大繰返しレートの数値制限
- 画像の明暗から「物理的に羽根が閉じた」ことを推定する自動光学試験

## 5. 属性仕様

`_report_shutter_capability(context)`は次をこの順序で問い合わせる。属性ごとの例外はログに残すが、
調査ログそのものの失敗でカメラ接続全体を直ちに落とさない。判定処理が最終的にエラー/未解決を決める。

| 属性名 | 制約/値 | 用途 |
|---|---|---|
| `Active Shutter` | Collection: None/Internal/External | 取得時に制御されるシャッター。構成照合の中心 |
| `Shutter Timing Mode` | Collection: Normal/Always Closed/Always Open/Open Before Trigger | 実際の開閉動作。自動darkにはAlways Closedが必要 |
| `Shutter Opening Delay` | Range | 開くまで待つPICam生値 |
| `Shutter Closing Delay` | Range | 閉じてから読出すまで待つPICam生値 |
| `Shutter Delay Resolution` | 読取り値（μs/生値1単位） | Delay生値とUIのmsを相互変換 |
| `Internal Shutter Type` | enum | 内蔵側が駆動できる型。存在証明には使わない |
| `Internal Shutter Status` | Not Connected/Connected/Overheated | 内蔵側の実接続・健全性 |
| `External Shutter Type` | enum（Vincent CS25/CS45等） | 外付け側が駆動できる型。存在証明には使わない |
| `External Shutter Status` | Not Connected/Connected/Overheated | 外付け側の実接続・健全性 |

ログ例（実値・候補は実機報告をそのまま出す）:

```text
[Shutter investigation/connect] Active Shutter: exists=True, relevant=True,
  writable=True, current=External, values=['None', 'Internal', 'External']
[Shutter investigation/connect] External Shutter Status: exists=True,
  relevant=True, writable=False, current=Connected
[Shutter investigation/connect] External Shutter Type: ... current=Vincent CS25
[Shutter investigation/connect] Shutter Timing Mode: ... current=Normal,
  values=['Normal', 'Always Closed', 'Always Open', 'Open Before Trigger']
[Shutter investigation/connect] Shutter Delay Resolution: ... current=1000
```

文字列はPICam/pylablibが実際に返す表記を正とし、比較時だけ空白・大文字小文字を正規化する。
UIやconfigからハードウェアへ書く値は、必ずその時点の`cap["values"]`から得た実文字列へ解決する。

## 6. 自動判定仕様

### 6.1 3つの概念を分離する

- `control_supported`: Timing Mode属性が存在し、書込み可能で、Always Closedと通常測定用モードを
  候補に持つ。
- `physical_state`: None / Connected / Overheated / Unresolved。Statusを第一根拠にする。
- `automation_ready`: control_supportedかつ、Active Shutterと対応Statusが一意に整合しConnectedで、
  config期待値とも一致する。

「属性がある」だけを`automation_ready=True`にしてはならない。

### 6.2 判定表

| 実機状況 | 判定 | 動作 |
|---|---|---|
| Timing Mode属性なし、またはAlways Closedなし | Unsupported | 自動dark無効。初回configは`expected: "None"`（制御不能という意味） |
| Active=None、両StatusがNot Connectedまたは非該当 | No shutter | 通常測定可、自動dark無効。初回configへNone保存 |
| Active=External、External Status=Connected、Timing Mode書込み可 | Connected/External | configと一致すれば自動dark可 |
| Active=Internal、Internal Status=Connected、Timing Mode書込み可 | Connected/Internal | configと一致すれば自動dark可 |
| 対応Status=Overheated | Fault/Overheated | 取得開始を禁止し、冷却・配線確認を要求 |
| Active=ExternalだがExternal Status=Not Connected | Configuration error | 自動dark不可、通常の手動測定は許可（Unresolvedと同じ重大度）。毎回警告し、Hardware Configurationで期待値を訂正するまで解消しない |
| TypeだけVincent、Status属性なし/読めない | Unresolved | 試験開閉せず自動dark無効。通常測定は可、設定確認を警告 |
| InternalとExternalの両方がConnected、Activeが読めない | Unresolved | ユーザーがActiveを明示するまで自動dark無効 |
| Status=ConnectedだがTiming Modeがread-only | Monitor only | 接続表示は可能だが自動dark無効 |

Active Shutter属性がなくても、Internal/Externalの片方だけが明確にConnectedならその側を推定できる。
ただし推定した側をPICamが実際に駆動する保証がないため、`automation_ready`はFalseとし手動確認を要求する。

### 6.3 「通信できない」の定義

外付けシャッターが独立したシリアル機器として応答するわけではない。ここでの通信確認はPICam経由の
`External Shutter Status=Connected`を意味する。Timing Modeのset→commit→readback成功も制御経路の
確認にはなるが、羽根が物理的に動いたことまでは証明しない。初回受入試験では、暗所または安全な光量で
Always Open/Always Closedの画像強度が明確に変わることを人が確認する。

## 7. `spectrometerConfig.json`仕様

既存のフラットな接続設定を壊さず、トップレベルへ`shutter`オブジェクトを追加する。

### 7.1 外付けシャッターありの例

```json
{
  "model": "PrincetonInstruments",
  "camera_serial_number": "0412060001",
  "shutter": {
    "expected": "External",
    "type": "Vincent CS25",
    "measurement_mode": "Always Open",
    "dark_mode": "Always Closed",
    "opening_delay_ms": 9.0,
    "closing_delay_ms": 9.0
  }
}
```

### 7.2 制御可能な同期シャッターなしの例

```json
{
  "model": "PrincetonInstruments",
  "shutter": {
    "expected": "None"
  }
}
```

### 7.3 判定不能の例

```json
{
  "model": "PrincetonInstruments",
  "shutter": {
    "expected": "Unresolved",
    "measurement_mode": "Always Open",
    "dark_mode": "Always Closed"
  }
}
```

### 7.4 各キーの意味

| キー | 必須 | 意味 |
|---|---|---|
| `expected` | 必須 | `None`/`Internal`/`External`/`Unresolved`。アプリから制御する同期シャッター構成の期待値。`None`は手動シャッターの物理的不在までは意味しない |
| `type` | Internal/External時は推奨 | PICam読戻し文字列。配線先・シャッター交換の検出に使う |
| `measurement_mode` | 自動制御時必須 | 通常取得に適用するモード。初期推奨は`Always Open` |
| `dark_mode` | 自動制御時必須 | 本実装では`Always Closed`固定。将来拡張用に明示 |
| `opening_delay_ms` | 属性が書込み可能なら保存 | 人が読めるms値。実機Rangeに合わせて変換・検証する |
| `closing_delay_ms` | 属性が書込み可能なら保存 | 同上 |

Status、Overheated、現在モードなどの**揮発状態はconfigに保存しない**。configは期待構成とアプリの
設定値であり、接続時snapshotはログ・Camera Statusで確認する。

### 7.5 初回作成・移行

1. `model != PrincetonInstruments`では`shutter`キーを追加しない。
2. PIかつ`shutter`キーがない場合、最初の正常なPICam接続後に一度だけ能力判定する。
3. Connectedを一意に確認できた場合、側・型・現在のDelay実値を保存し、
   `measurement_mode=Always Open`、`dark_mode=Always Closed`を設定する。
4. 制御不能またはシャッターなしを明確に確認できた場合、`expected=None`を保存する。
5. 判定不能なら`expected=Unresolved`と読めた範囲だけを保存し、警告する。
6. 初回保存では未知の既存キーを保持し、一時ファイル→`os.replace`等で原子的に書く。書込み失敗時は
   自動darkを有効にせず、GUIを測定可能状態へ遷移させる前にエラー表示する。
7. `--debug`では実験用configをモック値で汚さないため、自動追記しない。

カメラスレッドから直接JSONを書かない。`shutter_capability_ready`で判定結果と推奨configをGUIへ渡し、
GUIスレッドの`ConfigMixin`が保存する。同じ送信元から`shutter_capability_ready`を`init_finished`より先に
emitし、GUI側は保存/検証結果が確定するまで測定ボタンを有効にしない。

### 7.6 2回目以降の起動時照合

- `expected=External/Internal`:
  - Active側、対応Status=Connected、type（設定されている場合）が全て一致しなければ`automation_ready=False`
    （Configuration error、Section 6.2）とする。**カメラ初期化そのものは失敗させない** —
    自動darkのみ無効化し、通常の手動測定（Unresolvedと同じ重大度）は許可する。シャッター配線の
    緩みだけで実験全体が止まる事故を避けるため。毎回警告を出し、Hardware Configurationで期待値を
    訂正するかケーブルを直すまで解消しない。
  - Timing Modeが書けない、Always Closed/measurement_modeが候補にない場合も同様に
    `automation_ready=False`とし、カメラ自体は初期化する。
- `expected=None`:
  - 制御可能なConnectedシャッターを新たに検出した場合は構成変更として警告し、自動darkを無効化。
    物理構成を意図せず変えた可能性があるため、自動でconfigを書き換えない。
- `expected=Unresolved`:
  - 通常測定は許可、自動darkは無効。Hardware Configurationで明示するまで毎回警告する。
- Delayが現在のRange外:
  - 暗黙のtruncateはせず構成エラー。UIで実機Range内へ修正して保存する。

## 8. Delayの単位変換

PICam生値を`d_raw`、`Shutter Delay Resolution`を`r_us`とすると:

```text
delay_ms = d_raw * r_us / 1000
d_raw_requested = delay_ms * 1000 / r_us
```

- UIの最小・最大・stepも、Rangeの`min`/`max`/`inc`を同じ式でmsへ変換する。
- UIからの値は浮動小数誤差を考慮して最寄りの有効な生値stepへ量子化し、
  `_apply_attribute_value(..., truncate=False)`で適用する。
- commit後の生値を再度msへ変換した値をUIとconfigへ反映する。要求値をそのまま保存しない。
- Resolutionが存在しない、読めない、0以下の場合、Delay欄は単位を保証できないため編集不可とし、
  Camera Statusには`Unavailable (resolution unknown)`と出す。無条件にmsと仮定しない。
- Delay属性がread-onlyでも、換算した現在値は表示・metadata保存できる。

設定順序はOpening Delay→Closing Delay→Timing Modeとし、モード変更（実際の開閉につながり得る）を
最後に行う。modeだけの変更は既存`_apply_attribute_value()`をそのまま使える。3値を同時にApplyする
場合は、各値ごとにcommitすると途中状態が確定してしまうため、内部
`_apply_shutter_settings()`で全対象の前値を最初にsnapshotし、各pending値を順にsetして1回commit、
refresh、全値readbackする。set/commit失敗時は既存`_rollback_attribute_values()`へ最初のsnapshotを
渡し、best-effortで3値全てを戻す。

## 9. カメラバックエンド仕様

### 9.1 追加状態

`CameraThreadPI.__init__`へ次を追加する。

- `new_shutter_request: dict | None`
- `_shutter_request_seq`, `_shutter_applied_seq`
- `shutter_capability`, `current_shutter_settings`
- `automation_ready`
- debug用`mock_shutter_mode`, `mock_opening_delay_ms`, `mock_closing_delay_ms`

汎用コマンドキュー化は行わず、既存の`new_exposure`等と同じswap-and-clear型の要求フラグを使う。
ただしdark状態機械が古い完了通知を誤認しないよう、各要求に単調増加`request_id`と`purpose`
（`user`/`measurement`/`dark_close`/`dark_restore`/`recovery`）を付ける。

### 9.2 追加シグナル

```python
shutter_capability_ready = pyqtSignal(dict)
shutter_settings_applied = pyqtSignal(int, dict)   # request_id, actual settings
shutter_settings_failed = pyqtSignal(int, str)     # request_id, reason
```

能力dictには判定結果、全属性capability、換算済みDelay Range、推奨config、
`automation_ready`を含める。適用完了dictには実値読戻し後のmode/delay/active/type/statusを含める。
汎用`hardware_error`だけではどの要求が失敗したか分からないため、dark状態遷移には専用失敗シグナルを
使う。ユーザー向け総合エラー表示には従来通り`hardware_error`も併用してよい。

### 9.3 公開メソッド

```python
def update_shutter_mode(self, mode: str, purpose: str = "user") -> int
def update_shutter_delays(self, opening_ms: float, closing_ms: float,
                          purpose: str = "user") -> int
def update_shutter_settings(self, *, mode=None, opening_ms=None, closing_ms=None,
                            purpose="user") -> int
def get_shutter_snapshot(self) -> dict
```

最初の2つはUI用の薄いwrapperとし、内部では3つ目へ集約する。ハードウェアアクセスは呼出し元スレッドで
行わず、要求をロック下で保存してrun loopが処理する。現在値と同一の要求はcommitを省略するが、
`shutter_settings_applied`は必ず返し、呼出し側の待機を完了させる。

### 9.4 取得直前preflight

GUIの`take_single_spectrum()`/`start_measurement()`以外に、Calibration WindowとAPIもそれぞれ
`start_measuring()`を直接呼ぶ。呼出し側ごとにmode ensureを実装すると漏れが生じるため、
PIバックエンド自身が「停止→測定中」へ遷移した後、最初の`snap()`より前に共通preflightを行う。

- `start_measuring(acquisition_kind="normal")`は取得意図をロック下へ保存する。
- run loopは最初のframe前に、normalならconfigの`measurement_mode`、darkなら`Always Closed`をensureし、
  readbackとStatus=Connectedを確認する。
- 成功後に取得時シャッターsnapshotをシグナルでGUIへ渡し、それからsnapへ進む。
- 失敗時は1枚も取得せず`is_measuring=False`として`acquisition_failed`を通知する。
- 同じ取得を継続する各frameではpreflightを繰り返さない。PICam再接続後だけ再実行する。
- dark workflowは事前のclose完了待ちに加えて`acquisition_kind="dark"`を渡し、通常モードへ上書き
  されないようにする（防御を二重化する）。

引数なしの既存呼出しはnormalとして扱うため、Calibration/APIの既存コード変更を最小化できる。
Andorバックエンドの`start_measuring()`契約は変更しない。

### 9.5 `_report_shutter_capability(context)`

`_report_orientation_capability()`と同型だが、個別に属性を直接読むのではなく
`_query_attribute_capability()`を使用し、候補/Rangeも出力する。呼出し箇所は:

1. 初回`_connect_camera()`直後（`context="connect"`）
2. `_reopen_camera_connection()`直後（`context="reconnect"`）
3. Active Shutterを将来変更した直後（今回のmain UIでは変更しない）

Camera StatusのShutterセクションにもActive Shutter、Delay Resolution、換算済みms、
`automation_ready`と不成立理由を追加する。

### 9.6 接続復旧

`_reopen_camera_connection()`はclose前に現在のmode/delayをsnapshotし、再接続後に:

1. capability再取得
2. config期待値との再照合（ケーブル抜け/Overheatedなら復旧失敗）
3. Delay復元
4. Timing Mode復元
5. ROI等の残り設定復元

の順で処理する。dark取得中なら復元対象は`Always Closed`でなければならない。復旧後にPICam既定の
Normalへ戻ったままdarkを継続しない。復元に失敗した場合は既存のacquisition recovery上限に従って
取得を停止し、自動dark workflowにも失敗を通知する。

## 10. UI仕様

### 10.1 Main UIのShutterグループ（PIのみ）

- `Active shutter`: 読取り専用ラベル（External/Internal/None + type + status）
- `Timing mode`: コンボボックス
  - Normal
  - Always Open
  - Always Closed
- `Opening delay (ms)`: DoubleSpinBox
- `Closing delay (ms)`: DoubleSpinBox
- `Apply`: 3値を一要求として適用
- 状態ラベル: Ready / Applying / Not connected / Overheated / Unsupported / Unresolved

`Open Before Trigger`はcapabilityとCamera Statusには表示するが、外部トリガーを実装していないため
main comboには出さない。実機候補にないモードはcomboから除外する。Delay Range/step/decimalsは
Section 8の換算値から動的設定する。

- PI以外: グループを非表示。
- PIだがUnsupported/None: 状態説明を残して入力部を無効化。
- Unresolved: 手動測定のためmode表示は可能だが、自動darkボタンは無効化。
- Overheated/期待構成不一致: 測定開始ボタンも無効化。
- Sequential/APIによるUI lock中: 他の測定条件と同様に全シャッター入力を無効化。
- 取得中: PICam属性の`can_set_online`に頼らず変更不可とする。開閉中のsnap競合を避ける。

Apply成功時だけ実値をUIへ戻してconfigのmode/delayを更新する。失敗時は読める限り現在実値へ戻し、
configは変更しない。

### 10.2 Hardware Configuration

PI選択時だけShutter構成欄を追加する。

- Expected active shutter: Auto-unresolved / None / Internal / External
- Expected shutter type: capabilityから取得できれば候補、初期化失敗時用に編集可能文字列
- Measurement mode: Always Open（推奨）/Normal/Always Closed
- Dark mode: Always Closed（固定表示）

Expected/typeの変更は物理構成の契約変更なので再起動を要求する。mode/delayはMain UIから実値を
確認しながら変更することを基本とする。

## 11. 自動dark取得

### 11.1 状態遷移

```text
IDLE
  -> CLOSING_REQUESTED
  -> DARK_ACQUIRING
  -> RESTORE_REQUESTED
  -> SAVE_DIALOG
  -> IDLE

任意の途中状態で失敗/Terminate
  -> RESTORE_REQUESTED
  -> ERROR または IDLE
```

### 11.2 開始処理

`on_acq_bg_clicked()`は以下を行う。

1. 1Dモードであること、`automation_ready=True`、Status=Connected、非Overheatedを再確認する。
2. `_acquisition_gate`を取得する。復帰が完了するまで保持する。
3. `get_shutter_snapshot()`の**実モード**を`_bg_restore_settings`へ保存する。config値だけを保存しない。
4. UI条件（露光、積算、ROI、温度）とシャッターsnapshotを`_bg_acquisition_metadata`へ固定する。
5. `update_shutter_mode("Always Closed", purpose="dark_close")`を要求する。
6. 対応request_idの`shutter_settings_applied`でmodeがAlways Closedと読めた場合だけ、現行の単発積算
   初期化を行ってPIでは`thread.start_measuring(acquisition_kind="dark")`を呼ぶ。
7. set失敗、読戻し不一致、Status異常なら露光を開始せず復帰/エラー処理へ進む。

readbackは制御値の確認であって物理的閉鎖のセンサー確認ではない。Closing DelayはPICamが閉鎖待ちに
使うため、アプリ側で固定sleepを追加しない。実機受入試験で必要なら、機種固有の追加settle timeを
別configキーとして後から検討する。

### 11.3 完了・復帰処理

積算完了時は:

1. カメラ取得を停止するが、background workflowが取得ゲートを保持したままにする。
2. raw darkデータと取得時metadataを確保する。
3. `update_shutter_settings(**_bg_restore_settings, purpose="dark_restore")`を要求する。
4. 実値復帰成功後にゲートを解放し、保存ダイアログを開く。
5. 保存キャンセルでも復帰済みなので安全にIDLEへ戻る。

`finally`相当の共通cleanupを、次の全経路から必ず呼ぶ。

- 正常積算完了
- PICam取得エラー / all-zero recovery失敗
- shutter close失敗
- ユーザーがTerminate
- GUI例外（可能な範囲）

復帰失敗時は現在位置をUnknownとして通常取得を禁止し、Camera Status確認または再起動を要求する。
「復帰できなかったが測定ボタンだけ再び有効」という状態にしない。

**`on_acquisition_failed()`との統合（実装前に設計を詰める必要あり）。** 現行の
`acquisition_mixin.py`の`on_acquisition_failed()`は、`acquisition_failed`シグナル受信時に
即座に`stop_measurement()`を呼びゲートを解放する。これはdark取得中の失敗であっても復帰要求を
待たない。実装時はこの関数を、`_is_acquiring_bg`（または新state machineの同等フラグ）が真の間は
即時ゲート解放をスキップし、`update_shutter_settings(..., purpose="dark_restore")`を発行してから
復帰完了/タイムアウトを待ってゲート解放する分岐へ改修する。

なお、現行の`on_acquisition_failed()`は`_is_acquiring_bg`を一切クリアしない
（成功経路の`_process_completed_data()`でのみクリアされる: `acquisition_mixin.py`）。
そのため**現状でも**、background取得中に`acquisition_failed`が発生すると`_is_acquiring_bg=True`が
残留し、次の（無関係な）単発測定成功時に誤って背景保存ダイアログが開く潜在バグがある。
上記の統合作業でこのフラグのクリアも合わせて修正する。

### 11.4 手動darkへのフォールバック

シャッターなし/Unresolvedの機種では現行機能を完全に削除せず、ボタン文言を
`Acquire background (manual shutter)`とし、確認ダイアログで「手動で遮光した」ことを確認してから
取得できるようにする。自動darkと誤認しないよう、background metadataへ
`automation: "manual-confirmed"`を記録する。Unsupportedだからといってbackground取得自体を禁止しない。

## 12. 通常測定と機械シャッター保護

- 初期推奨`measurement_mode`は要望通り`Always Open`とする。
- 接続時のcapability調査ではモードを変更せず、試験開閉もしない。
- PIカメラスレッドの共通preflightで、通常取得開始前にmeasurement_modeを一度ensureし、実値読戻し
  完了後に露光する。GUI単発/連続、Sequential、Calibration、APIの全経路を対象にする。
- すでにAlways Openならset/commitを省略する。
- 連続測定の各フレームでNormal/Always Openを設定し直さない。
- dark取得時のみAlways Closedへ変更し、終了後はdark直前値（通常はAlways Open）へ戻す。
- Status=Overheatedなら新規取得を禁止する。取得中にOverheatedとなりPICamが停止した場合は既存の
  acquisition_failed経路へ統合する。

ただしProEM:1600(2)/(4)はフルフレームCCDであるため、Always Openでは読出し中も入射し続ける。
実験条件によっては縦スミア、信号上乗せ、露光時間の解釈差が生じ得る。実機受入試験でNormalと
Always Openを同一光源・同一露光・同一ROIで比較し、通常運用に問題があれば当該configの
`measurement_mode`をNormalへ変更する。寿命保護よりデータ妥当性を優先する。

## 13. 保存メタデータ

### 13.1 通常スペクトル

各取得開始時に読戻した実値を`last_acquisition_shutter_metadata`へ固定し、保存時の現在UI値ではなく
これを`metadata`へ渡す。

```json
{
  "active": "External",
  "type": "Vincent CS25",
  "status": "Connected",
  "timing_mode": "Always Open",
  "opening_delay_ms": 9.0,
  "closing_delay_ms": 9.0,
  "automation": "normal"
}
```

`DataFileIO._build_header()`へ、値がある場合だけ次を追加する（旧callerとの互換性を保つ）。

```text
Active Shutter: External
Shutter Type: Vincent CS25
Shutter Status: Connected
Shutter Timing Mode: Always Open
Shutter Opening Delay: 9 ms
Shutter Closing Delay: 9 ms
```

Sequential保存も既存の`_save_data_to_path()`を通るため同じmetadataを使用する。ただし、Sequentialは
`start_sequential()`が最初に一度`start_measuring()`を呼んだ後は`is_measuring=True`を保持し続ける
（`sequential_mixin.py`）。preflightは「未測定→測定中」の遷移時にしか走らない設計のため、実際には
**Sequential開始時に一度だけ確認した値**が、その連続実行中に保存される全ファイルへ書き込まれる
（モード自体はAlways Openのまま変化しないため実害はない）。「取得サイクルごとに再確認する」という
意味ではないことに注意する。したがって、Sequential実行中にExternal Shutter StatusがConnectedから
Overheated等へ変化しても、PICamの`snap()`がエラーを返さない限りアプリ側では検知できない。この
前提が許容できるかはSection 18.3の実機受入試験で確認する。

### 13.2 background JSON

`save_background()`へ`shutter_metadata=None`を追加し、payloadへ任意の`shutter`オブジェクトを保存する。

```json
{
  "shutter": {
    "active": "External",
    "type": "Vincent CS25",
    "status": "Connected",
    "timing_mode": "Always Closed",
    "opening_delay_ms": 9.0,
    "closing_delay_ms": 9.0,
    "automation": "automatic"
  }
}
```

`load_background()`は新キーをmetadataへ返す。旧ファイルにキーがなければ`shutter=None`として読める
後方互換にする。background mismatch判定では、新形式で`timing_mode != Always Closed`かつ
`automation=automatic`なら破損/不正ファイルとして警告する。旧ファイルやmanual-confirmedは
シャッター情報だけを理由に拒否しない。

## 14. debug仕様

PIモデルで`--debug`の場合、次を固定モックとする。

```text
Active Shutter: External
External Shutter Type: Vincent CS25
External Shutter Status: Connected
Internal Shutter Status: Not Connected
Timing Mode candidates: Normal / Always Closed / Always Open / Open Before Trigger
Current Timing Mode: Always Open
Delay Resolution: 1000 us
Opening/Closing raw range: 0..100, increment 1
Opening/Closing UI range: 0..100 ms, step 1 ms
```

- mode/delay Applyは約50 ms後に完了シグナルを返し、実値を更新する。
- Always Closedで取得したdebug spectrumはピークを出さず、bias pedestal + read noiseだけにする。
  これにより「閉じる前に取得した」競合を目視・テストで検出できる。
- `debug_shutter_failure`等を本番configへ追加しない。失敗経路の単体テストはFake camera/monkeypatchで行う。
- debug起動ではSection 7の通りconfigを自動更新しない。

## 15. エラー方針

| エラー | 重要度 | 動作 |
|---|---|---|
| config External/InternalとStatus不一致 | Configuration error（Unresolvedと同格） | 自動dark無効。通常の手動測定は許可、カメラはReadyにする。検出値を表示し毎回警告 |
| expected type不一致 | Configuration error（Unresolvedと同格） | 自動dark無効。通常の手動測定は許可。シャッター交換/設定更新を促す警告を出す |
| Overheated | Fatal while present | 取得禁止。冷却されConnectedへ戻るまで待つ/再接続 |
| Timing Mode set/commit失敗 | Operation fatal | 当該取得を開始しない。rollback後に実値再取得 |
| dark後の元モード復帰失敗 | Safety fatal | 以後の取得禁止、状態Unknown表示 |
| Delay configがRange外 | Configuration error | truncateせずApply/初期化失敗 |
| capabilityの一部が読めない | Unresolved | 自動dark無効、通常測定可、警告 |
| config自動保存失敗 | Configuration error | 自動dark無効。保存できるまでReady扱いにしない |
| 手動dark機種 | Normal fallback | 確認ダイアログ後に現行取得、manual metadata保存 |

## 16. 対象ファイル

```text
src/camera_princeton.py
  capability調査・判定、要求フラグ、set/readback、debug、再接続復元、Status拡張

src/ui.py
  Shutter UI構築、シグナル配線、初期状態

src/ui_mixins/acquisition_mixin.py
  通常取得開始前のmode ensure、完了時metadata snapshot、失敗/Terminate連携

src/ui_mixins/file_io_mixin.py
  自動dark状態機械、手動fallback、保存metadata受渡し

src/ui_mixins/sequential_mixin.py
  Shutter UIのlock/unlock

src/ui_mixins/config_mixin.py
  初回判定保存、原子的config保存、起動時構成エラー表示

src/menu/hardware_config_dialog.py
  PI Shutter期待構成欄、変更時restart-required判定

src/file_io.py
  通常スペクトルヘッダー/background JSONへの任意shutter metadata

work/work_PI_shutter.md
  本仕様、実機結果の追記先

tests/test_pi_shutter.py（新規、可能なら標準unittest）
  判定表、Delay換算、設定失敗、dark状態遷移の非実機テスト
```

Andorの`camera_andor.py`には制御APIを追加しない。UIは
`model == "PrincetonInstruments"`かつ`hasattr(thread, "shutter_capability_ready")`で有効化する。

## 17. 実装順序

---

### Step 1プロンプト: 調査ログのみ追加（P0、実機確認ゲート）

```text
FluoraPressée（work/work_PI_shutter.mdにPrinceton Instruments PICamシャッター制御の仕様がある）で、
このStep 1を実装して。作業前にCLAUDE.mdとwork/work_PI_shutter.md全体（特にSection 3.1, 5）を読むこと。

対象ファイル: src/camera_princeton.py, src/menu/camera_status_dialog.py, work/work_PI_shutter.md

やること:
1. camera_princeton.pyに_report_shutter_capability(context)を追加する。Section 5の表にある9属性
   （Active Shutter, Shutter Timing Mode, Shutter Opening/Closing Delay, Shutter Delay Resolution,
   Internal/External Shutter Type/Status）全てを既存の_query_attribute_capability()で問い合わせ、
   Section 5のログ例と同じ形式で出力する。既存の_report_orientation_capability(context)と同型で書く。
   属性ごとの例外はログに残すだけでカメラ接続全体を落とさない。
2. _connect_camera()直後(context="connect")と_reopen_camera_connection()直後(context="reconnect")の
   両方から呼び出す。
3. camera_status_dialog.pyのCamera Status表示にActive ShutterとShutter Delay Resolutionを追加する
   （既存のTiming Mode/Opening/Closing Delay/Internal/External Type/Statusはそのまま）。

やらないこと（重要）:
- シャッターへの値書き込み(set_attribute_value)は一切行わない。
- Section 6の判定ロジック(automation_ready等)は実装しない。ログを出すだけ。
- spectrometerConfig.jsonへの保存は行わない。
- Section 9〜13のシグナル・UI・状態機械には触れない。

完了条件:
- python main.py --debug が既存動作のまま問題なく起動する。
- 実機(ProEM:1600(2)、model="PrincetonInstruments")接続時、9属性のcapabilityログがコンソールに
  出力される。
- Camera StatusダイアログにActive ShutterとDelay Resolutionが表示される。
- 実機ログの結果をwork_PI_shutter.md Section 19へそのまま転記する。特に以下を確認して記録すること:
  Active Shutterが存在するか/現在値/候補値、External Shutter Status=Connectedか、pylablibが返す
  文字列表記が本書と一致するか、Delay ResolutionとOpening/Closing Rangeの実値。
- 実機での確認が取れるまでStep 2以降は着手しないこと。
```

---

### Step 2プロンプト: 判定・config契約（P0）

```text
FluoraPressée（work/work_PI_shutter.md参照）のPICamシャッター制御、Step 2を実装して。着手前に
work_PI_shutter.md Section 19に実機ログが記録済みか確認し、なければ作業を中断してユーザーに確認する
こと。Section 6, 7を読むこと。

対象ファイル: src/camera_princeton.py, src/ui_mixins/config_mixin.py, src/menu/hardware_config_dialog.py

やること:
1. Section 6.2の判定表を、capability snapshot(dict)を入力にcontrol_supported/physical_state/
   automation_readyを返す純粋関数として実装する(PyQt非依存、単体テスト可能な形にする)。
2. CameraThreadPIにshutter_capability_ready = pyqtSignal(dict)を追加し、init_finishedより前に
   emitする。Section 7.5の手順(初回はGUIスレッドのConfigMixinが原子的に保存、カメラスレッドから
   直接JSONを書かない)に従う。
3. 2回目以降の起動時照合をSection 7.6の通り実装する。ただしconfig External/InternalとStatus不一致、
   およびexpected type不一致は、カメラ初期化を失敗させない。自動darkのみ無効化し、通常の手動測定は
   許可する(Unresolvedと同格。Section 6.2の当該行とSection 15を必ず確認すること — 当初案から
   重大度を変更済み)。
4. hardware_config_dialog.pyのPIタブへExpected active shutter / Expected shutter type /
   Measurement mode / Dark modeの欄を追加する(Section 10.2)。Expected/typeの変更はrestart-required
   扱いにする。
5. config保存はSection 7.5の通り一時ファイル→os.replace等で原子的に行う。書込み失敗時は自動darkを
   有効にせずエラー表示する。既存のsave_config_to_file()は非原子的なので、新ヘルパーを追加するか
   置き換えるか判断し、理由をコミットメッセージ等に残す。

やらないこと:
- Delay換算・UI(Step 3)、実際のset/readback(Step 4)、自動dark状態機械(Step 5)は実装しない。
- Active Shutter属性そのものへの書き込みは行わない(Section 9.5)。

完了条件:
- --debug起動時、configのshutter自動追記が発生しない(Section 7.5手順7)。
- 非実機ユニットテストで、Section 6.2の判定表の主要な行(Unsupported/No shutter/Connected External/
  Overheated/Configuration error/Unresolved/Monitor only)が期待通りのautomation_readyになる。
- 実機接続で、spectrometerConfig.jsonにshutterオブジェクトが一度だけ自動生成されることを確認する。
```

---

### Step 3プロンプト: Delay換算とUI（P1）

```text
FluoraPressée（work/work_PI_shutter.md参照）のPICamシャッター制御、Step 3を実装して。Step 2の
判定・config保存が動作している前提で進める。着手前にSection 8, 10, 14を読むこと。

対象ファイル: src/camera_princeton.py, src/ui.py, src/ui_mixins/acquisition_mixin.py,
src/ui_mixins/sequential_mixin.py

やること:
1. Section 8の単位変換式(delay_ms = d_raw * r_us / 1000 とその逆)を実装し、UIのmin/max/stepも
   同じ式で変換する。Resolutionが存在しない/読めない/0以下ならDelay欄を編集不可にし、Camera
   Statusには"Unavailable (resolution unknown)"と表示する。単位をmsと仮定しない。
2. ui.pyにSection 10.1のPI Shutterグループ(Active shutterラベル、Timing modeコンボ[Normal/
   Always Open/Always Closed]、Opening/Closing delay DoubleSpinBox、Applyボタン、状態ラベル)を
   追加する。PI以外のモデルでは非表示にする。
3. capabilityから候補にないモード(Open Before Triggerなど)はコンボへ出さない。Camera Statusには
   表示してよい。
4. Section 14のdebugモック値を実装する(Active=External, type=Vincent CS25, Status=Connected/
   Not Connected, Timing Mode候補, Resolution=1000等)。mode/delay Applyは約50ms後に完了シグナルを
   返す。
5. UIロック(Sequential/API lock中は無効化、取得中は変更不可、Unsupported/Unresolved/Overheated時
   の表示)をSection 10.1の通り実装する。

やらないこと:
- 実際にハードウェアへset/commitする経路(Step 4)はまだ実装しない。Applyを押しても実機へは
  書き込まれない状態でよい(--debugのモックApplyは動いてよい)。
- 自動dark状態機械(Step 5)は実装しない。

完了条件:
- Resolution=1000, raw range 0..100, inc 1 → UI 0..100 ms, step 1 ms になることを単体テストで確認。
- Resolution=10, raw=250 → 2.5 ms、往復変換で同じ有効raw値に戻ることを確認。
- Resolution不明/0のときDelay欄が編集不可になることを確認。
- python main.py --debug でPI configにするとShutterグループが表示され、mode/delay Applyから約
  50ms後にUIへ実値が反映される(Section 18.2の1・2)。
- Andor/--debugの通常起動にPI Shutter UIが干渉しないことを確認する(Section 18.1)。
```

---

### Step 4プロンプト: 設定適用・読戻し（P0、実機開閉あり）

```text
FluoraPressée（work/work_PI_shutter.md参照）のPICamシャッター制御、Step 4を実装して。これは実機の
シャッターを実際に開閉させるStepなので、安全な光量・暗所で実施できることを先に確認すること。着手前に
Section 9を読むこと。Step 1〜3が完了している前提で進める。

対象ファイル: src/camera_princeton.py, src/ui_mixins/acquisition_mixin.py

やること:
1. CameraThreadPIにSection 9.1の追加状態(new_shutter_request, _shutter_request_seq,
   _shutter_applied_seq, shutter_capability, current_shutter_settings, automation_ready,
   debug用mock_*)と、Section 9.2の3シグナル(shutter_capability_ready, shutter_settings_applied,
   shutter_settings_failed)を追加する。既存のnew_exposureと同じswap-and-clear方式を使い、各要求に
   monotonic request_idとpurpose(user/measurement/dark_close/dark_restore/recovery)を付ける。
2. Section 9.3の公開メソッド(update_shutter_mode, update_shutter_delays, update_shutter_settings,
   get_shutter_snapshot)を実装する。mode単独は既存の_apply_attribute_value()を使う。3値同時は
   新規_apply_shutter_settings()で、Opening Delay→Closing Delay→Timing Modeの順にsetし1回
   _commit_parameters()、_refresh_attributes()、全値readbackする。set/commit失敗時は既存の
   _rollback_attribute_values()で前値へbest-effort復帰する。
3. 現在値と同一の要求はcommitを省略するが、shutter_settings_appliedは必ず返す。
4. Section 9.4の共通preflightをrun()のis_measuring分岐(was_measuringがFalse→Trueに変わる
   タイミング)に追加する。normalならconfigのmeasurement_mode、darkならAlways Closedをensureし、
   readbackとStatus=Connectedを確認してから最初のsnap()へ進む。失敗時は1枚も取得せず
   is_measuring=Falseとしてacquisition_failedを通知する。同じ取得を継続する各frameではpreflightを
   繰り返さない。
5. start_measuring()にacquisition_kind: str = "normal"引数を追加する(デフォルトで既存呼び出し元は
   変更不要)。
6. 取得中はPICamのcan_set_onlineに頼らずUI側で変更不可にする(Step 3で追加したUIロックと連動)。

やらないこと:
- 自動dark状態機械(on_acq_bg_clickedの改修、Step 5)はまだ実装しない。このStepではpreflightと
  Apply経路の単体動作確認が目的。
- metadata保存(Step 6)、recovery統合(Step 7)はまだ実装しない。

完了条件(実機必須):
- 安全な光量・暗所で、Timing ModeをAlways Open/Always Closedへ切り替え、Statusとともに読戻し値が
  UIへ反映されることを確認する。異音・開閉不良がないことを確認する。
- 非実機テストで、同一mode要求はcommitされず完了シグナルだけ返ること、commit失敗時に前値へ
  rollbackされconfig/UIが要求値にならないことを確認する。
- 確認結果をwork_PI_shutter.md Section 19へ追記する。
```

---

### Step 5プロンプト: 自動dark状態機械（P0）

```text
FluoraPressée（work/work_PI_shutter.md参照）のPICamシャッター制御、Step 5を実装して。Step 4の
set/readback経路が実機で確認済みである前提で進める。着手前にSection 11を必ず読むこと。特に
Section 11.3末尾の「on_acquisition_failed()との統合(実装前に設計を詰める必要あり)」の段落 —
_is_acquiring_bgが失敗経路でクリアされない既存の潜在バグを含む — を読んでから着手すること。

対象ファイル: src/ui_mixins/file_io_mixin.py, src/ui_mixins/acquisition_mixin.py

やること:
1. Section 11.1の状態遷移(IDLE→CLOSING_REQUESTED→DARK_ACQUIRING→RESTORE_REQUESTED→SAVE_DIALOG→
   IDLE、失敗時はRESTORE_REQUESTED経由でERROR/IDLE)を実装する。
2. on_acq_bg_clicked()をSection 11.2の手順に書き換える: ゲート取得→get_shutter_snapshot()の
   実モードを_bg_restore_settingsへ保存→UI条件とシャッターsnapshotを_bg_acquisition_metadataへ
   固定→update_shutter_mode("Always Closed", purpose="dark_close")→対応request_idの
   shutter_settings_appliedでAlways Closedと確認できた場合のみ
   thread.start_measuring(acquisition_kind="dark")。
3. 完了処理をSection 11.3の通り実装する: 積算完了→raw dark確保→
   update_shutter_settings(**_bg_restore_settings, purpose="dark_restore")→復帰成功後にゲート
   解放して保存ダイアログ。
4. 正常完了・PICam取得エラー・shutter close失敗・ユーザーTerminate・GUI例外の全経路が共通の
   restore/cleanup処理を通るようにする。特にon_acquisition_failed()を、_is_acquiring_bgが真の間は
   即時ゲート解放をスキップし、dark_restoreの完了/タイムアウトを待ってから解放する分岐に改修する。
   あわせて、失敗経路で_is_acquiring_bgを必ずFalseへ戻す(既存の潜在バグ修正を兼ねる)。
5. 古いrequest_idの完了通知でdark取得が始まらないようにする。
6. シャッターなし/Unresolved機種向けに、ボタン文言を"Acquire background (manual shutter)"にし、
   確認ダイアログ後に現行の取得を行うfallbackを維持する(Section 11.4)。background metadataへ
   automation: "manual-confirmed"を記録する。

やらないこと:
- スペクトル/背景ファイルへのmetadata保存の本実装(Step 6。ここでは_bg_acquisition_metadataを
  保持するところまででよい)。
- recovery(PICam再接続時の復元、Step 7)は次のStepで扱う。

完了条件:
- 実機(安全な光量)で、Acquire backgroundがAlways Closed→取得→Always Open復帰の順で動作し、
  異音・取得順序の破綻がないことを確認する。
- background保存キャンセル後もAlways Openへ復帰していることを確認する。
- background取得中にTerminateして元モードへ戻ることを確認する。
- 非実機テストで、dark取得成功/失敗/Terminateの全てでrestoreがちょうど1回だけ要求されること、
  restore完了前にacquisition gateが解放されないことを確認する。
```

---

### Step 6プロンプト: metadata（P1）

```text
FluoraPressée（work/work_PI_shutter.md参照）のPICamシャッター制御、Step 6を実装して。Step 4の
preflightとStep 5のdark状態機械が動作している前提で進める。着手前にSection 13を読むこと。特に
Section 13.1本文中の「Sequential連続測定中はpreflightが実質1回しか走らない」という注記を踏まえ、
「取得サイクルごとに再確認する」という誤解をコードに持ち込まないこと(Sequential開始時に一度だけ
確認した値が連続実行中の全保存ファイルへ書き込まれるのが正しい挙動)。

対象ファイル: src/file_io.py, src/ui_mixins/file_io_mixin.py, src/ui_mixins/acquisition_mixin.py

やること:
1. 各取得開始時(preflight成功直後)に読戻した実値をlast_acquisition_shutter_metadataへ固定し、
   保存時点のUI値ではなくこれを使う。
2. DataFileIO._build_header()へ、値がある場合だけSection 13.1のフィールド(Active/Type/Status/
   Timing Mode/Opening/Closing Delay)を追加する。値がない旧callerとの互換性を保つ(キーが無ければ
   何も出力しない)。
3. save_background()にshutter_metadata=None引数を追加し、Section 13.2のJSON構造でpayloadへ
   shutterオブジェクトを保存する。
4. load_background()が新キーをmetadataへ返すようにし、旧ファイル(キーなし)はshutter=Noneとして
   読める後方互換を維持する。
5. background mismatch判定に、新形式でtiming_mode != Always Closedかつautomation="automatic"なら
   破損/不正ファイルとして警告するロジックを追加する。旧ファイルやmanual-confirmedはシャッター
   情報だけを理由に拒否しない。

やらないこと:
- recovery統合(Step 7)はまだ実装しない。

完了条件:
- 非実機テストで、旧background JSON(shutterキーなし)が読め、新background JSONはshutter
  metadataを往復できることを確認する。
- 実機/--debugで保存したスペクトルとbackground JSONに、取得時のshutterメタデータが正しく
  記録されることを確認する。
```

---

### Step 7プロンプト: recovery・総合検証（P0）

```text
FluoraPressée（work/work_PI_shutter.md参照）のPICamシャッター制御、Step 7(最終Step)を実装して。
Step 1〜6が全て実機で動作確認済みである前提で進める。着手前にSection 9.6, 12, 18.3, 20を読むこと。

対象ファイル: src/camera_princeton.py, 関連mixins

やること:
1. _reopen_camera_connection()へ、Section 9.6の順序(capability再取得→config期待値との再照合→
   Delay復元→Timing Mode復元→ROI等の残り設定復元)でシャッター復元を追加する。dark取得中の再接続は
   Always Closedへ復元する(PICam既定のNormalへ戻ったままdarkを継続しない)。復元失敗時は既存の
   acquisition recovery上限に従い取得を停止し、自動dark workflowにも失敗を通知する。
2. dark中のPICamエラー、ケーブル切断、Overheated相当の失敗を実機またはfake camera/monkeypatchで
   テストする。
3. ProEM:1600(2)で、同一光源・露光・ROI・積算でNormalとAlways Openを比較し、ピーク位置・積分強度・
   背景・縦方向スミア(2D)を確認する。問題があれば当該configのmeasurement_modeをNormalへ変更する
   (Section 12)。
4. 連続測定中(Sequential等でis_measuringを保持したまま)に外付けシャッターのケーブルを抜く、または
   過熱を模擬し、PICamのsnap()がエラーを返して既存のacquisition_failed経路へ正しく合流するか確認
   する(Section 18.3の11番)。返さない場合、連続測定中のStatus変化検知に追加のポーリング設計が
   必要かどうかを判断し記録する。
5. Section 18.3の受入チェックリスト(1〜11)を実機で通しで実行する。
6. 実機結果をSection 19へ記録し、本仕様冒頭の「実機確認待ち」の記載を更新する。

完了条件:
- Section 18.3の受入チェックリストが全項目パスする。
- Section 20の未決事項6点(Active Shutterの存在、External Statusの挙動、enum文字列一致、Delay
  Resolution/Range実値、Always Closedの物理閉鎖確認、Always Openのデータ品質許容性)が全て確定し、
  work_PI_shutter.mdへ反映されている。
```

## 18. テスト・受入基準

### 18.1 非実機テスト

- capability判定表の全行が期待状態になる。
- Resolution=1000、raw range 0..100、inc 1がUI 0..100 ms、step 1 msになる。
- Resolution=10、raw=250が2.5 msになり、往復変換で同じ有効raw値へ戻る。
- Resolution不明/0でDelay編集が無効になる。
- mode候補にAlways Closedがない場合automation_readyにならない。
- config External、実機Not Connected/Overheated/type mismatchがFatalになる。
- 同一mode要求はcommitせず完了シグナルを返す。
- commit失敗時に前値rollbackし、config/UIを要求値にしない。
- dark close完了シグナル前には`start_measuring()`が呼ばれない。
- dark取得成功、取得失敗、Terminateの全てでrestoreが1回だけ要求される。
- 古いrequest_idの完了通知でdark取得が始まらない。
- restore完了前にacquisition gateが解放されない。
- 旧background JSONが読め、新background JSONはshutter metadataを往復できる。
- Andor/debug通常起動にPI Shutter UIが干渉しない。

### 18.2 `--debug`手動確認

1. PI config + `python main.py --debug`でShutterグループが表示される。
2. mode/delay Apply後、読戻し値がUIへ反映される。
3. Acquire backgroundでAlways Closed→dark風データ→Always Openの順になる。
4. background保存キャンセル後もAlways Openへ復帰している。
5. Sequential/API lock中にシャッター設定を変更できない。
6. debugにより`spectrometerConfig.json`のshutter期待構成が自動変更されない。

### 18.3 ProEM:1600²実機受入

1. Section 19の全属性ログを採取する。
2. カメラ本体の手動ノブではなく、対象外付けシャッターの配線・型を確認する。
3. `External Shutter Status=Connected`、`Active Shutter=External`を確認する。
4. 暗所・安全な光量でAlways Open/Always Closedを各1回だけ切り替え、画像平均値が明確に変わることを
   確認する。異常音、開閉不良、Overheatedがないことを確認する。
5. 自動darkを取得し、手動遮光darkとbias/ノイズ水準が整合することを確認する。
6. 同一光源・露光・ROI・積算でNormalとAlways Openを比較し、ピーク位置、積分強度、背景、縦方向
   スミア（2D）を確認する。
7. 連続測定中に毎フレーム開閉していないことを音/状態で確認する。
8. External shutter cableを抜いた状態で次回起動し、config mismatchにより取得が禁止されることを確認する。
9. background取得中にTerminateし、元モードへ戻ることを確認する。
10. 保存スペクトルとbackground JSONに**取得時**modeが記録されることを確認する。
11. 連続測定中（Sequential等でis_measuringを保持したまま）に外付けシャッターのケーブルを抜く、
    または過熱状態を模擬し、PICamの`snap()`が例外/エラーを返して既存の`acquisition_failed`経路へ
    正しく合流するか確認する。返さない場合、連続測定中のStatus変化検知には別途ポーリング等の追加
    設計が必要になるため、その要否をここで判断する。

## 19. 実機調査記録（未実施）

以下をProEM:1600²接続時に埋める。

```text
Camera model:
Camera serial:
PICam Runtime version:
pylablib version:

Active Shutter:
  exists / relevant / writable / current / values =
Shutter Timing Mode:
  exists / relevant / writable / current / values =
Shutter Opening Delay:
  exists / relevant / writable / current / min / max / inc =
Shutter Closing Delay:
  exists / relevant / writable / current / min / max / inc =
Shutter Delay Resolution:
  exists / relevant / writable / current =
Internal Shutter Type:
Internal Shutter Status:
External Shutter Type:
External Shutter Status:

Physical shutter model/cabling:
Always Open optical check:
Always Closed optical check:
Normal vs Always Open data-quality comparison:
Final measurement_mode decision:
```

## 20. 実装開始条件と未決事項

Step 1の読取り専用ログ追加は直ちに実装可能。それ以降の自動開閉を本番有効化する前に、最低限次を
実機で確定する。

1. ProEM:1600²で`Active Shutter`が存在するか。
2. 外付けケーブル接続時に`External Shutter Status`がConnectedになるか。
3. pylablibが返すenum文字列が本書の表記と一致するか。
4. Delay ResolutionとOpening/Closing Rangeの実値。
5. Always Closedのreadback後、物理的にも閉じるか。
6. ProEM:1600²の通常スペクトルでAlways Openが科学的に許容できるか。

この6点が確認できない間は、`expected=Unresolved`、自動dark無効、現行の手動遮光background取得を
維持する。特に「ProEMはフレームトランスファーなのでAlways Openで問題ない」という理由では
1600²のdefaultを確定しない。
