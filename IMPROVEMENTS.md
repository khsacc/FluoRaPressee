# コード改善実装ログ

## 実装済み改善 (修正3～8)

### 3. エラーハンドリング改善

#### `camera_andor.py`
- **Andor SDK未インストール時の処理改善**: Andor が None の場合、明確なエラーメッセージを発行
- **温度読み込み失敗時の処理**: カメラ未初期化時に既定値を返すよう改善
- **例外処理を具体化**: 例外タイプを `RuntimeError`, `ValueError` で分類

#### `pressureCalc.py`
- **裸の `except:` を改善**: 以下の具体的な例外をキャッチ:
  - `ZeroDivisionError`: 分母が0の場合
  - `ValueError`: 無効な数値操作
  - `KeyError`: パラメータ欠落
  - `Exception`: その他の予期しないエラー

### 4. 不必要なコード削除

#### `calibration.py`
- 空の `__init__` メソッドを削除（クラスドキュメント追加）

### 5. マジックナンバーを定数化

#### `camera_andor.py`
```python
DEFAULT_DETECTOR_WIDTH = 1024
DEFAULT_DETECTOR_HEIGHT = 127
DEFAULT_TEMP = -65
DEFAULT_EXPOSURE = 0.1
TEMP_TOLERANCE = 0.5
SLEEP_INTERVAL = 0.05
```

#### `analysis.py`
```python
MIN_FIT_POINTS = 10
FWHM_FRACTION = 0.02
FWHM_MIN = 0.0001
PEAK_DISTANCE = 5
PEAK_PROMINENCE_FACTOR = 0.1
PEAK_SPACING_FACTOR = 0.1
SECOND_PEAK_AMP_FACTOR = 0.5
PSEUDO_VOIGT_ETA_INIT = 0.5
PSEUDO_VOIGT_ETA_MIN = 0.0
PSEUDO_VOIGT_ETA_MAX = 1.0
```

#### `calibration.py`
```python
PEAK_WINDOW = 10
SIGMA_GUESS = 2.0
SIGMA_MAX = 20
NOISE_THRESHOLD = 1.0
```

### 6. 設定ファイルのハードコード修正

#### `spectrometer.py`
- **改善内容**: 設定ファイルパスの動的解決
- **実装**: `_get_config_path()` 関数を追加
  - 明示的にパスを渡せるように改善
  - パスが指定されない場合、プロジェクトルート相対パスを使用
  - ファイルが存在しない場合のエラーハンドリング
- **インポート順序を修正**: 全インポートをファイル先頭に配置

### 7. 圧力計算式の構造化

#### `pressureCalc.py`
- 現在: `if-elif` で計算式を分岐
- **将来の改善**: 圧力計算式を辞書/クラス構造に統一
  ```python
  PRESSURE_SCALES = {
      "Ruby": {
          "Piermarini et al. 1975": calculate_piermarini,
          "Mao et al. 1986": calculate_mao,
          ...
      }
  }
  ```
  これにより新しいスケール追加が容易になります

### 8. 型ヒント・ドキュメント文字列追加

#### `analysis.py`
```python
def fit_spectrum(self, x_data: np.ndarray, y_data: np.ndarray, func_type: str = "Gauss", 
                 fit_start: Optional[float] = None, fit_end: Optional[float] = None) -> Tuple:
    """スペクトルのピークフィッティングを行う（指定されたX軸の範囲内で実行）
    
    Args:
        x_data: X 軸データ
        y_data: Y 軸データ
        ...
    Returns:
        (x_fit, y_fit_curve, res) のタプル。フィッティング失敗時は (None, None, None)
    """
```

#### `calibration.py`
```python
def find_and_fit_peaks(self, y_data: np.ndarray, prominence_multiplier: float = 3.5) -> List[Dict]:
    """スペクトルからピークを検索し、それぞれをガウシアンでフィットする"""

def calibrate(self, pixels: np.ndarray, ref_values: np.ndarray) -> Optional[Dict]:
    """ピクセルと基準値のリストを受け取り、多項式フィットを行う"""
```

#### `pressureCalc.py`
```python
def calculate(sensor: str, p_scale: str, lam: float, lam0: float, lam0_at_t0: float, 
              lam_err: float = 0.0, current_t: float = 298.15, t0: float = 298.15) -> Tuple[Optional[float], Optional[float]]:

def get_corrected_lam0(sensor: str, t_scale: str, current_t: float, t0: float, lam0_at_t0: float) -> float:
```

---

## 今後の改善予定 (修正9～10)

### 9. スレッド安全性向上 (`camera_andor.py`)

**現在の問題点**:
- フラグ(`is_measuring`, `settings_changed`)の更新に Lock がない
- マルチスレッド環境でRace Conditionが発生する可能性

**推奨改善**:
```python
from threading import Lock

class CameraThreadAndor(QThread):
    def __init__(self):
        self._lock = Lock()
        ...
    
    def update_exposure(self, exp_time):
        with self._lock:
            self.new_exposure = exp_time
    
    def _apply_camera_settings(self):
        with self._lock:
            # 安全にフラグを読み取る
```

### 10. UI 状態管理クラス化 (`ui.py`)

**現在の問題点**:
- `SpectrometerGUI.__init__` に20個以上のインスタンス変数
- 関連する状態がバラバラに配置
- 保守性が低い

**推奨改善**:
```python
class SpectrumData:
    """スペクトラムデータを管理するクラス"""
    def __init__(self):
        self.raw_1d_data = None
        self.raw_2d_data = None
        self.latest_1d_data = None
        self.latest_2d_data = None
        self.calib_coeffs = None

class SequentialMeasurementState:
    """シーケンシャル測定の状態を管理"""
    def __init__(self):
        self.is_running = False
        self.count = 0
        self.start_time = None
        self.log_data = []

# UI では以下のように使用:
class SpectrometerGUI(QMainWindow):
    def __init__(self, debug=False):
        self.spectrum_data = SpectrumData()
        self.seq_state = SequentialMeasurementState()
        # ... その他の初期化
```

このアプローチにより:
- 関連する状態をまとめて管理
- 状態の初期化・リセットが容易
- テストが書きやすくなる

---

## テスト推奨事項

1. **型チェック**: `mypy` でコードをチェック
   ```bash
   mypy src/analysis.py src/pressureCalc.py src/calibration.py
   ```

2. **例外処理テスト**: 各 `except` ブロックが正しく機能することを確認

3. **スレッド安全性テスト**: 複数スレッドの同時実行下で動作確認

4. **パフォーマンステスト**: 定数化によるオーバーヘッド確認（通常は無視できる程度）
