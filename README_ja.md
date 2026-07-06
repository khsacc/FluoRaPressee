# FluoraPressée: Andor Spectrometer Control & Analysis GUI

* Author: Hiroki Kobayashi (Geochemical Research Center, The University of Tokyo). 
    * https://orcid.org/0000-0002-3682-7558 
    * E-mail as of 2026: hiroki (at) eqchem.s.u-tokyo.ac.jp

Andor製のカメラ（検出器）および分光器を制御し、スペクトルのリアルタイム取得からバックグラウンド補正、キャリブレーション、ピークフィッティング、そして高圧実験における圧力計算までを一貫して行うためのPythonベースのGUIアプリケーションです。

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
    * 利用可能な函数は、Gaussian, Lorentzian, Pseudo Voigt, Double Gaussian, Double Lorentzian, Double Pseudo Voigt の6種類
* 圧力計算ウィンドウを開く



### 横軸較正画面（「Calibrate x-axis」ボタンをクリックして開く）

![](manuals/img/CalibrationWindow.png)

* 標準試料のスペクトルを取得し、ピーク検索、Gaussian函数によるピークフィット、波長の較正までを行えます。


### 横軸較正補助画面

![](manuals/img/CalibrationHelperWindow.png)

* よく使うネオンの波長領域のスペクトル（事前に測定してプログラム中に保存したもの）を表示してピークの帰属の参考にできます。


### 圧力計算画面（「Open pressure calculator」ボタンをクリックして開く）

![](manuals/img/PressureCalculator.png)

* 横軸が波長のモードの場合、蛍光スケール、横軸がRaman shiftのモードの場合、Ramanスケールを用いた圧力計算が可能です。使用できるスケールは以下の通りです
* 蛍光スケール
    * ルビー（Cr<sup>3+</sup>:Al<sub>2</sub>O<sub>3</sub>）
        * 圧力シフト
            * Shen et al., <i>High Press. Res.</i> (2020) [DOI: 10.1080/08957959.2020.1791107](https://doi.org/10.1080/08957959.2020.1791107)
            * Holzapfel, <i>J. Appl. Phys.</i> (2003) [DOI: 10.1063/1.1525856](https://doi.org/10.1063/1.1525856)
            * Mao et al., <i>J. Geophys. Res.</i> (1986) [DOI: 10.1029/JB091iB05p04673](https://doi.org/10.1029/JB091iB05p04673)
            * Piermarini et al., <i>J. Appl. Phys.</i> (1975) [DOI: 10.1063/1.321957](10.1063/1.321957)
        * 温度シフト
            * 0 - 600 K, Ragan et al., <i>J. Appl. Phys.</i> (1992) [DOI: 10.1063/1.351951](https://doi.org/10.1063/1.351951)
            * 296 - 800 K, Datchi et al., <i>High Press. Res.</i> (2007) [DOI: 10.1080/08957950701659593](https://10.1080/08957950701659593)
    * Sm<sup>2+</sup>:SrB<sub>4</sub>O<sub>7</sub>
        * 圧力シフト
            * Datchi et al., <i>J. Appl. Phys.</i> (1997) [calibrated using the MXB1986 ruby scale] [DOI: 10.1063/1.365025](https://doi.org/10.1063/1.365025)
            * Datchi et al., <i>High Press. Res.</i> (2007) [calibrated using the DO2007 ruby scale] [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)
        * 温度シフト
            * Datchi et al., <i>High Press. Res.</i> (2007) [DOI: 10.1080/08957950701659593](https://doi.org/10.1080/08957950701659593)
* Raman スケール
    * <sup>13</sup>C diamond first order
        * Schiferl et al., <i>J. Appl. Phys.</i> (1997) [DOI: 10.1063/1.366268](https://doi.org/10.1063/1.366268)
    * Cubic BN TO
        * Datchi et al. <i>Phys. Rev. B.</i> (2004) [DOI: 10.1103/PhysRevB.69.144106](https://doi.org/10.1103/PhysRevB.69.144106)
    * Zircon B<sub>1g</sub>
        * Schmidt et al., <i>Am. Min.</i> (2013) [DOI: 10.2138/am.2013.4143](https://doi.org/10.2138/am.2013.4143)
        * Takahashi et al., <i>J. Raman Spectrosc.</i> (2024) [DOI: 10.1002/jrs.6663](https://doi.org/10.1002/jrs.6663)




## 必須環境 (Requirements)

* **OS**: Windows 10 / 11 (Andor SDKの動作環境に依存します)
* **Python**: Python 3.8 以上, 3.13以下
* **Hardware**:
  * Andor製 カメラ（検出器）
  * Andor製 分光器
* **Drivers/SDK**:
  * Andor SDK (ドライバパッケージがPCにインストールされている必要があります)

## インストール方法 

1. コマンドプロンプトまたはPowerShellを開きます。
2. 必要なPythonパッケージをインストールします。
    ```bash
    pip install PyQt5 pyqtgraph numpy scipy pylablib
    ```
3. Andor SDKが正しくインストールされていることを確認します。
4. ディレクトリに、``spectrometerConfig.json``を作成し、以下の例を参考にしながら、``ShamrockCIF.dll``ファイルのパス、回折格子の情報および検出器の情報を記録します。``spectrometerConfig.json``を更新したのち、再度起動すれば、新しい内容が反映されます。


```json
{
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
    "flip_x": true
}
```

##  使い方 

    ```bash
    python ui.py
    ```
※ ハードウェアを接続せずにUIのテストだけを行いたい場合は、デバッグモードで起動できます。

    ```bash
    python ui.py --debug
    ```

##  保存されるファイルの形式

### データファイル

#### Background を差し引かない場合

```
# Date: 2026-04-15 20:22:03
# Grating: 1200 grooves/mm
# Spectrometer Mode: Wavelength
# Center Wavelength: 694.0 nm
# Acquisition Time: 0.1 s
# Accumulations: 1
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
# Date: 2026-04-15 21:05:42
# Grating: 1200 grooves/mm
# Spectrometer Mode: Wavelength
# Center Wavelength: 694.0 nm
# Acquisition Time: 2.0 s
# Accumulations: 1
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

### Background file
```json
{
    "detector_settings": {
        "mode": "1D Spectrum (Custom ROI)",
        "roi_start": 100,
        "roi_end": 140
    },
    "acquisition_time": "1.00",
    "signal": [
        1085,
        1089,
        1088,
        1090, ...
    ]
}
```

### Configuration file
```json
{
    "timestamp": "2026-04-15 21:01:52",
    "spectrometer_settings": {
        "grating_grooves_per_mm": "1200",
        "center_value": 694.0,
        "unit": "Wavelength"
    },
    "detector_settings": {
        "mode": "1D Spectrum (Custom ROI)",
        "roi_start": 113,
        "roi_end": 125
    },
    "calibration_coefficients": {
        "c0": 673.3405851432854,
        "c1": 0.020990883361968825,
        "c2": -2.889725985123467e-07
    }
}
```







## 謝辞
このプログラムは私が作成したものですが、機能やデザインに関する多くのアイデアは、私がStefan Klotz氏との共同研究のためにフランス・パリ・ソルボンヌ大学-CNRS UMR 7590 IMPMCに滞在した際によく使用していた、[Rubycond](https://github.com/CelluleProjet/Rubycond) プログラムから着想されたものです。Rubycondの開発者であるYiuri Garino 氏に感謝申し上げます。またこのプログラムは東京大学大学院理学系研究科附属地殻科学実験施設 鍵裕之
教授・小松一生准教授の研究室で開発されました。最後に、開発に際してGeminiに多くの有用な助けを借りたことを申し添えます。