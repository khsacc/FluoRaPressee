# FluoraPressée: Spectrometer Control & Analysis GUI

* Author: Hiroki Kobayashi (Geochemical Research Center, The University of Tokyo). 
    * https://orcid.org/0000-0002-3682-7558 
    * E-mail as of 2026: hiroki (at) eqchem.s.u-tokyo.ac.jp

Andor製またはPrinceton Instruments製のカメラ（検出器）および分光器を制御し、スペクトルのリアルタイム取得からバックグラウンド補正、キャリブレーション、ピークフィッティング、そして高圧実験における圧力計算までを一貫して行うためのPythonベースのGUIアプリケーションです。

## スクリーンショット


### メイン画面

![](manuals/img/MainWindowFull.jpg)

* スペクトルの取得、保存
    * 単発測定および連続測定
    * インターバルを指定した連続保存・連続解析もできます。
* 分光器の基本的な制御（回折格子の変更、中心位置の変更）
* ROI の設定、イメージモード（CCDで取得した画像をそのまま出力）への切り替え
* バックグラウンドの取得と差し引き
* ピーク函数を用いたフィッティング
* 圧力計算ウィンドウを開く



### 横軸較正画面（「Calibrate x-axis」ボタンをクリックして開く）

![](manuals/img/CalibrationWindow.png)

* 標準試料のスペクトルを取得し、ピーク検索、Gaussian函数によるピークフィット、波長の較正までを行えます。


### 横軸較正補助画面

![](manuals/img/CalibrationHelperWindow.png)

* よく使うネオンの波長領域のスペクトル（事前に測定してプログラム中に保存したもの）を表示してピークの帰属の参考にできます。


### フィッティング

* Pseudo-Voigt, Moffat, Gaussian, Lorenzian の4種類の関数に対応
* ピーク数の最大は５まで。



### 圧力計算画面（「Open pressure calculator」ボタンをクリックして開く）

![](manuals/img/PressureCalculator.png)

* 横軸が波長のモードの場合、蛍光スケール、横軸がRaman shiftのモードの場合、Ramanスケールを用いた圧力計算が可能です。使用できるスケールは以下の通りです
* 蛍光スケール
    * ルビー（Cr<sup>3+</sup>:Al<sub>2</sub>O<sub>3</sub>）
        * 圧力シフト
            * Shen et al., <i>High Press. Res.</i> (2020) [DOI: 10.1080/08957959.2020.1791107](https://doi.org/10.1080/08957959.2020.1791107)
            * Kraus et al., <i>Phys. Rev. B.</i> (2016) [DOI: 10.1103/PhysRevB.93.134105](https://doi.org/10.1103/PhysRevB.93.134105)
            * Sokolova et al., <i>Russ. Geol. Geophys.</i> (2013) [DOI: 10.1016/j.rgg.2013.01.005](https://doi.org/10.1016/j.rgg.2013.01.005)
            * Jacobsen et al., <i>Am. Min.</i> (2008) [for helium pressure medium, calibrated against the MgO scale] [DOI: 10.2138/am.2008.2988](https://doi.org/10.2138/am.2008.2988)
            * Dorogokupets and Oganov, <i>Phys. Rev. B.</i> (2007) [DOI: 10.1103/PhysRevB.75.024115](https://doi.org/10.1103/PhysRevB.75.024115)
            * Holzapfel, <i>J. Appl. Phys.</i> (2003) [DOI: 10.1063/1.1525856](https://doi.org/10.1063/1.1525856)
            * Mao et al., <i>J. Geophys. Res.</i> (1986) [DOI: 10.1029/JB091iB05p04673](https://doi.org/10.1029/JB091iB05p04673)
            * Piermarini et al., <i>J. Appl. Phys.</i> (1975) [DOI: 10.1063/1.321957](https://doi.org/10.1063/1.321957)
        * 温度シフト
            * 0 - 600 K, Ragan et al., <i>J. Appl. Phys.</i> (1992) [DOI: 10.1063/1.351951](https://doi.org/10.1063/1.351951)
            * 0 - 600 K, Yen and Nicol, <i>J. Appl. Phys.</i> (1992) [DOI: 10.1063/1.351950](https://doi.org/10.1063/1.351950)
            * 0 - 296 K [低温域], Datchi et al., <i>High Press. Res.</i> (2007) [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)
            * 296 - 900 K [高温域], Datchi et al., <i>High Press. Res.</i> (2007) [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)
            * 0 - 300 K, Kobayashi et al., unpublished
    * Sm<sup>2+</sup>:SrB<sub>4</sub>O<sub>7</sub>
        * 圧力シフト
            * Datchi et al., <i>J. Appl. Phys.</i> (1997) [calibrated using the MXB1986 ruby scale] [DOI: 10.1063/1.365025](https://doi.org/10.1063/1.365025)
            * Datchi et al., <i>High Press. Res.</i> (2007) [calibrated using the DO2007 ruby scale] [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)
            * Rashchenko et al., <i>J. Appl. Phys.</i> (2015) [0-0線(λ1)・0-1線(λ2–λ4)の4系統から選択可] [DOI: 10.1063/1.4918304](https://doi.org/10.1063/1.4918304)
        * 温度シフト
            * 296 - 900 K, Datchi et al., <i>High Press. Res.</i> (2007) [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)
    * Sm<sup>2+</sup>:SrFCl
        * 圧力シフト
            * Lorenz et al., <i>High Press. Res.</i> (1994) [DOI: 10.1080/08957959408203170](https://doi.org/10.1080/08957959408203170)
            * Shen et al., <i>High Press. Res.</i> (2021) [DOI: 10.1080/08957959.2021.1931168](https://doi.org/10.1080/08957959.2021.1931168)
            * Shen et al., <i>High Press. Res.</i> (1991) [DOI: 10.1080/08957959108245510](https://doi.org/10.1080/08957959108245510)
        * 温度シフト
            * 20 - 650 K, Lorenz et al., <i>High Press. Res.</i> (1994) [DOI: 10.1080/08957959408203170](https://doi.org/10.1080/08957959408203170)
* Raman スケール
    * <sup>13</sup>C diamond first order
        * 圧力シフト
            * Schiferl et al., <i>J. Appl. Phys.</i> (1997) [DOI: 10.1063/1.366268](https://doi.org/10.1063/1.366268)
            * Mysen and Yamashita, <i>Geochim. Cosmochim. Acta</i> (2010) [温度依存項を内包、基準温度T<sub>0</sub> = 298.15 K (25℃) 固定] [DOI: 10.1016/j.gca.2010.05.004](https://doi.org/10.1016/j.gca.2010.05.004)
    * Cubic BN TO
        * 圧力シフト
            * Datchi et al., <i>Phys. Rev. B.</i> (2004) [温度依存項を内包、有効範囲 300–723 K] [DOI: 10.1103/PhysRevB.69.144106](https://doi.org/10.1103/PhysRevB.69.144106)
            * Kawamoto et al., <i>Rev. Sci. Instrum.</i> (2004) [DOI: 10.1063/1.1765756](https://doi.org/10.1063/1.1765756)
        * 温度シフト
            * 300 - 1000 K, Kawamoto et al., <i>Rev. Sci. Instrum.</i> (2004) [DOI: 10.1063/1.1765756](https://doi.org/10.1063/1.1765756)
    * Zircon B<sub>1g</sub>
        * 圧力シフト
            * Schmidt et al., <i>Am. Min.</i> (2013) [DOI: 10.2138/am.2013.4143](https://doi.org/10.2138/am.2013.4143)
            * Takahashi et al., <i>J. Raman Spectrosc.</i> (2024) [DOI: 10.1002/jrs.6663](https://doi.org/10.1002/jrs.6663)
        * 温度シフト
            * 296 - 1223 K, Schmidt et al., <i>Am. Min.</i> (2013) [DOI: 10.2138/am.2013.4143](https://doi.org/10.2138/am.2013.4143)
            * 294 - 1078 K, Takahashi et al., <i>J. Raman Spectrosc.</i> (2024) [DOI: 10.1002/jrs.6663](https://doi.org/10.1002/jrs.6663)
    * Quartz 464 cm<sup>-1</sup>
        * 圧力シフト
            * Schmidt and Ziemann, <i>Am. Min.</i> (2000) [23℃付近、2次式、0 < Δν ≤ 20 cm<sup>-1</sup>（~2.1 GPaまで）] [DOI: 10.2138/am-2000-11-1216](https://pubs.geoscienceworld.org/msa/ammin/article/85/11-12/1725/133600/In-situ-Raman-spectroscopy-of-quartz-A-pressure)
            * Schmidt and Ziemann, <i>Am. Min.</i> (2000) [100–560℃、線形近似 9 cm<sup>-1</sup>/GPa] [DOI: 10.2138/am-2000-11-1216](https://pubs.geoscienceworld.org/msa/ammin/article/85/11-12/1725/133600/In-situ-Raman-spectroscopy-of-quartz-A-pressure)
        * 温度シフト
            * 77.15 - 833.15 K (-196 - 560℃), Schmidt and Ziemann, <i>Am. Min.</i> (2000) [DOI: 10.2138/am-2000-11-1216](https://pubs.geoscienceworld.org/msa/ammin/article/85/11-12/1725/133600/In-situ-Raman-spectroscopy-of-quartz-A-pressure)
    * Quartz 128 cm<sup>-1</sup>
        * 圧力シフト
            * Li et al., <i>Chem. Geol.</i> (2025) [温度依存項を内包、基準温度T<sub>0</sub> = 296.15 K (23℃) 固定、有効範囲 296.15–973.15 K] [DOI: 10.1016/j.chemgeo.2024.122558](https://doi.org/10.1016/j.chemgeo.2024.122558)




## 必須環境 (Requirements)

* **OS**: Windows 10 / 11 (Andor SDK・Princeton Instruments PICam Runtime のいずれもWindows専用のため)
* **Python**: Python 3.9 以上, 3.13以下
* **Hardware**: 以下のいずれかの組み合わせに対応しています（起動時の設定ウィザードでどちらかを選択します）
  * Andor製 カメラ（検出器）+ Andor製 分光器（Kymera / Shamrock シリーズ、``ShamrockCIF.dll`` 経由で制御）
  * Princeton Instruments製 カメラ（検出器、PICam対応機種）+ Princeton Instruments製 分光器（Acton SP シリーズ、シリアル(COMポート)通信で制御）
* **Drivers/SDK**:
  * Andorの場合: Andor SDK (ドライバパッケージがPCにインストールされている必要があります)
  * Princeton Instrumentsの場合: PICam Runtime（カメラSDK。分光器側は追加ドライバ不要でシリアルポート経由で通信します）

## インストール方法 

1. リポジトリをクローンしたのち、``setup.bat``をダブルクリック（またはコマンドプロンプト/PowerShellから実行）します。
   プロジェクトフォルダ内に仮想環境``.venv``が作成され、``requirements.txt``に記載された必要なPythonパッケージ
   （``PyQt6``, ``pyqtgraph``, ``numpy``, ``scipy``, ``pylablib``, ``pyserial``、および後述のAPI機能用の
   ``fastapi``, ``uvicorn``, ``pydantic``）がすべて自動的にインストールされます。
   手動でインストールする場合は、作成した仮想環境内で ``pip install -r requirements.txt`` を実行してください。
2. 使用する装置メーカーに応じて、SDK/ドライバを正しくインストールします。
   * Andorの場合: Andor SDK
   * Princeton Instrumentsの場合: PICam Runtime（カメラ用）。分光器（Acton SP シリーズ）はシリアル接続のため、PC側のCOMポート番号を確認しておきます。
3. ``spectrometerConfig.json``が存在しない状態でアプリを初めて起動すると、セットアップウィザードが自動的に開きます。
   1. メーカー選択（Andor / Princeton Instruments）
   2. 接続設定（Andor: ``ShamrockCIF.dll`` のパス。Princeton Instruments: COMポート、PICam Runtimeのパス、カメラのシリアル番号）。
      「Read parameters from connected hardware」ボタンで、接続済みの実機からこれらの値や回折格子構成を自動取得することもできます。
   3. 回折格子（grooves/mm）、``flip_x``（スペクトルの左右反転）、冷却温度などの初期値

   ウィザード完了後、``spectrometerConfig.json``がプロジェクトルートに生成されます（ウィザードをキャンセルした場合は、Andor用のデフォルト設定が生成されます）。内容は以下のようなJSONファイルで、直接編集して再起動すれば変更が反映されます。

### Andor の場合

```json
{
    "model": "Andor",
    "dll_path": "C:\\Program Files\\Andor SDK\\Shamrock64\\ShamrockCIF.dll",
    "grating": [
        {
            "index": 1,
            "grooves": 2400,
            "defaultROI": {"from": 80, "to": 100}
        },
        {
            "index": 2,
            "grooves": 1800,
            "defaultROI": {"from": 115, "to": 130}
        },
        {
            "index": 3,
            "grooves": 1200,
            "defaultROI": {"from": 113, "to": 125}
        }
    ],
    "flip_x": true,
    "default_temperature": -65,
    "default_fan_mode": "full"
}
```

### Princeton Instruments の場合

```json
{
    "model": "PrincetonInstruments",
    "com_port": "COM3",
    "PIcam_dll_path": "C:\\Program Files\\Princeton Instruments\\PICam\\Runtime",
    "camera_serial_number": "0412060001",
    "grating": [
        {
            "index": 1,
            "grooves": 1200,
            "defaultROI": {"from": 100, "to": 140}
        },
        {
            "index": 2,
            "grooves": 1800,
            "defaultROI": {"from": 100, "to": 140}
        }
    ],
    "flip_x": false,
    "default_temperature": -65
}
```

``default_fan_mode``はAndor SDK2の冷却ファン制御に固有の項目のため、Princeton Instrumentsの設定には含まれません。カメラのシリアル番号（``camera_serial_number``）は、接続されているカメラが1台のみであれば省略できます。

##  使い方 

``FluoRaPressee_run.bat``をダブルクリック（またはコマンドプロンプト/PowerShellから実行）すると、``setup.bat``で作成した仮想環境を使ってアプリが起動します。

<!-- ※ ハードウェアを接続せずにUIのテストだけを行いたい場合は、``FluoRaPressee_run_debug.bat``を使うとデバッグモードで起動できます。

macOS/Linux上でUI開発のみ行う場合（ハードウェア制御は非対応）は、``./setup.sh``と``./FluoRaPressee_run_debug.sh``を使用してください。 -->

### Analysis Modeをスタンドアロンで起動する

保存済みの1Dスペクトルを読み込んでフィッティングや圧力計算を行うAnalysis Modeは、装置制御用のメイン画面を起動せず、単独で使用できます。プロジェクトのルートフォルダで次のコマンドを実行してください。

Windows（``setup.bat``で作成した仮想環境を直接使用する場合）:

```powershell
.venv\Scripts\python.exe analysis_main.py
```

仮想環境をすでに有効化している場合:

```bash
python analysis_main.py
```

macOS/Linux（``setup.sh``で作成した仮想環境を直接使用する場合）:

```bash
.venv/bin/python analysis_main.py
```

Analysis Modeの起動には、カメラ・分光器の接続、装置SDK、``spectrometerConfig.json``は必要ありません。未較正のpixel軸データでもフィッティングは可能ですが、圧力計算には波長またはRaman shiftで較正されたデータが必要です。

## API機能（同一LAN内の他PCからの操作）

校正やROI設定などの基本操作をGUI内で完結させたのち、画面下部の「API Server」パネルで
**Start API Server** を押すと、同一LAN内の他PCからHTTP経由で測定をトリガーできるようになります。
起動するとURLとAPIキーが表示されるので、それを使いたい相手に共有してください。APIサーバーが
起動している間、GUI側の測定・設定系操作はロックされ（プロットの表示設定等は引き続き操作可）、
**Stop API Server** を押すとローカルでの操作権が戻ります。

エンドポイント一覧・リクエスト/レスポンスの詳細は [manuals/API.md](manuals/API.md) を参照してください。

##  保存されるファイルの形式

### データファイル

#### Background を差し引かない場合

```
# Timestamp: 2026-04-15 20:22:03
# Grating: 1200 grooves/mm
# Spectrometer Mode: Wavelength
# Centre Wavelength: 694.0 nm
# Acquisition Time: 0.1 s
# Accumulations: 1
# Calibration Coefficients (c0, c1, c2: y = c0 + c1x + c2x^2): 673.3405851432854, 0.020990883361968825, -2.889725985123467e-07
# ROI Start (Vertical Pixel): 113
# ROI End (Vertical Pixel): 125
# Measurement Mode: 1D Spectrum (Custom ROI)
# Wavelength_or_Pixel,Intensity
673.63,1122
673.65,1130
673.671,1126
673.691,1126
673.712,1125
673.732,1132
673.753,1128
...
```

#### Background を差し引く場合
```
# Timestamp: 2026-04-15 21:05:42
# Grating: 1200 grooves/mm
# Spectrometer Mode: Wavelength
# Centre Wavelength: 694.0 nm
# Acquisition Time: 2.0 s
# Accumulations: 1
# Calibration Coefficients (c0, c1, c2: y = c0 + c1x + c2x^2): 673.3405851432854, 0.020990883361968825, -2.889725985123467e-07
# ROI Start (Vertical Pixel): 113
# ROI End (Vertical Pixel): 125
# Measurement Mode: 1D Spectrum (Custom ROI)
# Wavelength_or_Pixel,Intensity_Subtracted,Intensity_Raw,Background
673.341,2,1031,1029
673.362,3,1035,1032
673.383,3,1031,1028
673.404,-7,1029,1036
673.425,-1,1032,1033
673.446,5,1036,1031
673.467,0,1030,1030
673.488,-2,1032,1034
673.508,1,1031,1030
673.529,-3,1029,1032
...
```

較正係数が未適用の場合、``Calibration Coefficients`` の行は ``# Calibration Coefficients: None`` となります。横軸がRaman shiftモードの場合、``Spectrometer Mode: Raman shift`` に加えて ``Excitation Wavelength`` と ``Centre Raman shift`` の行が挿入されます。また、測定時のカメラ・分光器の詳細情報（機種名・シリアル番号・ROI・ビニング・冷却温度など、Andor / Princeton Instruments いずれの場合も共通のスキーマで記録されます）を持つ ``hardware_metadata`` 行が末尾に付加されることがあります。

### Background file
```json
{
    "detector_settings": {
        "mode": "1D Spectrum (Custom ROI)",
        "roi_start": 100,
        "roi_end": 140
    },
    "acquisition_time": "1.00",
    "accumulations": 1,
    "detector_temperature": -65.0,
    "hardware_metadata": { "...": "..." },
    "signal": [
        1085,
        1089,
        1088,
        1090, ...
    ]
}
```

### Configuration file

Configurationは校正ダイアログの ``Save and apply`` でアプリケーション管理領域へ自動保存されます。
任意の保存先・ファイル名を毎回指定する必要はありません。同じ装置、grating、centre position、ROIで
再度保存すると新しいversionがactiveになり、以前のversionは履歴として保持されます。メイン画面の
``Load previous configuration`` は、接続中の装置と互換性があるactive configurationだけを通常表示し、
必要な場合だけ ``Show version history`` で旧versionを表示します。

Configurationはgrating、centre position、ROI、装置互換性と横軸calibrationを一体として扱います。
露光時間、積算数、試料・物質名、background、fitting条件は測定ごとに変更する値なので含みません。
保存場所はOSのユーザー別application data領域にある ``FluoraPressee/configurations`` です。個々の
JSON recordを正本とし、一覧検索には全JSONを読み込まずSQLite catalogを使用します。
装置互換性は、保存時にserial numberを取得できた場合はその完全一致を必須とし、取得できないbackendでは
modelの完全一致へfallbackします。旧形式の任意保存calibration JSONはこのcatalogへimportされず、
ファイル自体は削除されませんがLoad画面の対象にはなりません。

```json
{
    "schema_version": 1,
    "configuration_id": "cfg_...",
    "slot_id": "slot_...",
    "created_at": "2026-07-22T15:30:00+09:00",
    "compatibility": {
        "spectrometer_model": "SP-2750",
        "spectrometer_serial_number": "SPEC-001",
        "camera_model": "DU-401",
        "camera_serial_number": "CAM-001"
    },
    "spectrometer": {
        "grating_index": 2,
        "grating_grooves_per_mm": 1200,
        "target_center_wavelength_nm": 694.0,
        "actual_center_wavelength_nm": 693.9998
    },
    "detector": {
        "roi_mode": "1d_roi",
        "roi_start": 113,
        "roi_end": 125
    },
    "calibration": {
        "unit": "Wavelength",
        "excitation_wavelength_nm": null,
        "coefficients": {
            "c0": 673.3405851432854,
            "c1": 0.020990883361968825,
            "c2": -2.889725985123467e-07
        }
    }
}
```

``configuration_id`` は変更されない特定version、``slot_id`` は同一のgrating・centre・ROI条件を表します。
外部自動化から利用する将来のAPIも、GUIのLoad画面と同じcatalog summaryと互換性判定を使用できる構造です。







## 謝辞

このプログラムは私が作成したものですが、機能やデザインに関する多くのアイデアは、私がStefan Klotz氏との共同研究のためにフランス・パリ・ソルボンヌ大学-CNRS UMR 7590 IMPMCに滞在した際によく使用していた、[Rubycond](https://github.com/CelluleProjet/Rubycond) プログラムから着想されたものです。Rubycondの開発者であるYiuri Garino 氏に感謝申し上げます。またこのプログラムは東京大学大学院理学系研究科附属地殻科学実験施設 鍵裕之
教授・小松一生准教授の研究室で開発されました。最後に、開発に際してClaude CodeおよびGeminiに助けを借りたことを申し添えます。
