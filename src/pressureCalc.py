import numpy as np
from scipy.integrate import quad
from typing import Tuple, Optional

class PressureCalculator:
    """高圧下の圧力計算を行うクラス。複数のセンサーと圧力スケールに対応"""

    SENSORS = {
        "ruby": {
            "label": "Ruby",
            "unit": "nm",
            "initial_value": 694.300,
        },
        "sm_srb4o7": {
            "label": "Sm2+:SrB4O7",
            "unit": "nm",
            "initial_value": 685.410,
        },
        "diamond_13c_1st_order": {
            "label": "13C diamond 1st order",
            "unit": "cm-1",
            "initial_value": 1287.79,
        },
        "cubic_bn_to": {
            "label": "Cubic BN TO",
            "unit": "cm-1",
            "initial_value": 1058.3,
        },
        "zircon_b1g": {
            "label": "Zircon B1g",
            "unit": "cm-1",
            "initial_value": 1008.6,
        },
    }

    PRESSURE_SCALES = {
        "ruby": {
            "ruby_shen_2020": {"label": "Shen et al. 2020", "requires_temperature": False},
            "ruby_dorogokupets_oganov_2007": {"label": "Dorogokupets and Oganov 2007", "requires_temperature": False},
            "ruby_holzapfel_2003": {"label": "Holzapfel 2003", "requires_temperature": False},
            "ruby_mao_1986": {"label": "Mao et al. 1986", "requires_temperature": False},
            "ruby_piermarini_1975": {"label": "Piermarini et al. 1975", "requires_temperature": False},
        },
        "sm_srb4o7": {
            "sm_srb4o7_datchi_1997_mxb1986": {"label": "0-0 line: Datchi et al. 1997 (MXB1986)", "requires_temperature": False},
            "sm_srb4o7_datchi_2007_do2007": {"label": "0-0 line: Datchi et al. 2007 (DO2007)", "requires_temperature": False},
            "sm_srb4o7_rashchenko_2018_lam1": {"label": "0-0 line (lam1): Rashchenko et al. 2018", "requires_temperature": False},
            "sm_srb4o7_rashchenko_2018_lam2": {"label": "0-1 line (lam2): Rashchenko et al. 2018", "requires_temperature": False},
            "sm_srb4o7_rashchenko_2018_lam3": {"label": "0-1 line (lam3): Rashchenko et al. 2018", "requires_temperature": False},
            "sm_srb4o7_rashchenko_2018_lam4": {"label": "0-1 line (lam4): Rashchenko et al. 2018", "requires_temperature": False},
        },
        "diamond_13c_1st_order": {
            "diamond_13c_schiferl_1997": {
                "label": "Schiferl et al. 1997",
                "requires_temperature": True,
                "valid_temp_range": (0, 1500.0),
            },
            "diamond_13c_mysen_yamashita_2010": {
                "label": "Mysen and Yamashita 2010",
                "requires_temperature": True,
            },
        },
        "cubic_bn_to": {
            "cubic_bn_kawamoto_2004": {"label": "Kawamoto et al. 2004", "requires_temperature": False},
            "cubic_bn_datchi_2004": {
                "label": "Datchi et al. 2004",
                "requires_temperature": True,
                "valid_temp_range": (300, 723),
            },
        },
        "zircon_b1g": {
            "zircon_schmidt_2013": {"label": "Schmidt et al. 2013", "requires_temperature": False},
            "zircon_takahashi_2024": {"label": "Takahashi et al. 2024", "requires_temperature": False},
        },
    }

    TEMPERATURE_SCALES = {
        "ruby": {
            "ruby_kobayashi_unpublished": {"label": "Kobayashi et al. unpublished", "valid_range": (0, 300)},
            "ruby_yen_nicol_1992": {"label": "Yen and Nicol 1992", "valid_range": (0, 600)},
            "ruby_ragan_1992": {"label": "Ragan et al. 1992", "valid_range": (0.0, 600.0)},
            "ruby_datchi_2007_ht": {"label": "Datchi et al. 2007 HT", "valid_range": (296, 900)},
            "ruby_datchi_2007_lt": {"label": "Datchi et al. 2007 LT", "valid_range": (0, 296)},
        },
        "sm_srb4o7": {
            "sm_srb4o7_datchi_2007": {"label": "Datchi et al. 2007", "valid_range": (296, 900.0)},
        },
        "cubic_bn_to": {
            "cubic_bn_kawamoto_2004": {"label": "Kawamoto et al. 2004", "valid_range": (300, 1000)},
        },
        "zircon_b1g": {
            "zircon_schmidt_2013": {"label": "Schmidt et al. 2013", "valid_range": (296, 1223)},
            "zircon_takahashi_2024": {"label": "Takahashi et al. 2024", "valid_range": (294, 1078)},
        },
    }

    @staticmethod
    def get_sensors_for_unit(unit: str):
        return [key for key, meta in PressureCalculator.SENSORS.items() if meta["unit"] == unit]

    @staticmethod
    def get_pressure_scale_label(sensor: str, p_scale: str) -> str:
        return PressureCalculator.PRESSURE_SCALES.get(sensor, {}).get(p_scale, {}).get("label", p_scale)

    @staticmethod
    def get_temperature_scale_label(sensor: str, t_scale: str) -> str:
        return PressureCalculator.TEMPERATURE_SCALES.get(sensor, {}).get(t_scale, {}).get("label", t_scale)

    @staticmethod
    def pressure_scale_requires_temperature(*, sensor: str, p_scale: str) -> bool:
        return PressureCalculator.PRESSURE_SCALES.get(sensor, {}).get(p_scale, {}).get("requires_temperature", False)

    @staticmethod
    def get_temp_valid_range(*, sensor: str, t_scale: Optional[str] = None,
                             p_scale: Optional[str] = None) -> Tuple[Optional[float], Optional[float]]:
        if p_scale is not None:
            p_meta = PressureCalculator.PRESSURE_SCALES.get(sensor, {}).get(p_scale, {})
            if p_meta.get("requires_temperature"):
                return p_meta.get("valid_temp_range", (None, None))

        if t_scale is not None:
            t_meta = PressureCalculator.TEMPERATURE_SCALES.get(sensor, {}).get(t_scale, {})
            return t_meta.get("valid_range", (None, None))

        return (None, None)

    @staticmethod
    def is_temp_in_range(*, sensor: str, temp: float, t_scale: Optional[str] = None,
                         p_scale: Optional[str] = None) -> Tuple[bool, Tuple]:
        """温度がセンサーの有効範囲内にあるか確認

        全引数キーワード専用・すべて必須。

        Args:
            sensor: センサー名
            temp: 温度値
            t_scale: 温度補正スケール
            p_scale: 温度入力が必須の圧力スケール

        Returns:
            (有効性, (最小値, 最大値)) のタプル
        """
        rng = PressureCalculator.get_temp_valid_range(sensor=sensor, t_scale=t_scale, p_scale=p_scale)
        if rng[0] is None or rng[1] is None:
            return True, (None, None)

        is_valid = rng[0] <= temp <= rng[1]
        return is_valid, rng


    @staticmethod
    def calculate(*, sensor: str, p_scale: str, lam: float, lam0: float,
                  lam0_at_t0: Optional[float] = None, lam_err: float = 0.0,
                  current_t: float = 298.15, t0: float = 298.15) -> Tuple[Optional[float], Optional[float]]:
        """圧力を計算する。全引数キーワード専用。

        Args:
            sensor: センサー名(必須)
            p_scale: 圧力スケール名(必須)
            lam: 現在のピーク位置(必須)
            lam0: ゼロ圧力ピーク位置(必須)。温度補正を使わない場合はこれがそのまま使われる
            lam0_at_t0: 基準温度T0でのゼロ圧力ピーク位置(任意)。P-T方程式を直接使うスケール
                (例: Cubic BN TOのDatchi et al. 2004)でのみ実際に使われる。省略時(None)は
                `lam0` と同じ値とみなす
            lam_err: `lam` の誤差(任意、既定0.0)
            current_t: 現在の温度、単位K(任意、既定298.15 = 25℃)
            t0: 基準温度、単位K(任意、既定298.15)

        Returns:
            (圧力[GPa], 圧力誤差[GPa]) のタプル。計算できない場合は (None, None)
        """
        if lam0_at_t0 is None:
            lam0_at_t0 = lam0
        try:

            # --- common formula ---
            def calc_mao_type(lam, lam0, lam_err, A, B, A_err, B_err):
                r = lam / lam0

                p = (A / B) * (r**B - 1.0)

                dp_lam = (A / lam0) * r**(B - 1.0) * lam_err
                dp_A = ((r**B - 1.0) / B) * A_err
                dp_B = (
                    (A / B**2)
                    * (B * r**B * np.log(r) - (r**B - 1.0))
                    * B_err
                )

                dp = np.sqrt(dp_lam**2 + dp_A**2 + dp_B**2)

                return p, dp

            # --- Ruby Scales ---
            if sensor == "ruby":

                if p_scale == "ruby_piermarini_1975":
                    p = 2.746 * (lam - lam0)
                    return p, 2.746 * lam_err
                
                elif p_scale == "ruby_mao_1986":
                    # No errors in the original paper
                    return calc_mao_type(lam, lam0, lam_err, 1904.0, 7.665, 0, 0)
                
                elif p_scale == "ruby_holzapfel_2003":
                    A =1820
                    B = 14
                    C = 7.3
                    A_err = 30
                    B_err = 2
                    C_err = 0
                    r = lam / lam0

                    p = (A / (B+C) ) * (np.exp(((B+C)/C) * (1-r**(-C))) - 1)


                    X = (B + C)/C * (1 - r**(-C))
                    expX = np.exp(X)

                    # 偏微分
                    dp_dA = (expX - 1)/(B + C)

                    dX_dB = (1/C)*(1 - r**(-C))
                    dp_dB = -A/(B + C)**2 * (expX - 1) + (A/(B + C))*expX*dX_dB

                    dX_dC = (
                        -B/C**2 * (1 - r**(-C))
                        + (B + C)/C * r**(-C) * np.log(r)
                    )
                    dp_dC = -A/(B + C)**2 * (expX - 1) + (A/(B + C))*expX*dX_dC

                    dX_dlam = (B + C)/lam * r**(-C)
                    dp_dlam = (A/(B + C)) * expX * dX_dlam

                    # 合成誤差
                    dp = np.sqrt(
                        (dp_dA * A_err)**2 +
                        (dp_dB * B_err)**2 +
                        (dp_dC * C_err)**2 +
                        (dp_dlam * lam_err)**2
)
                    return p, dp
                
                elif p_scale == "ruby_dorogokupets_oganov_2007":
                    A=1884
                    m = 5.5
                    dlam=lam - lam0
                    p = A * (dlam / lam0) * (1 + m * dlam / lam0)

                    x = dlam / lam0
                    dp = abs(A / lam0 * (1 + 2*m*x)) * lam_err
                    return p, dp

                elif p_scale == "ruby_shen_2020":
                    A, B = 1870.0, 5.63
                    dA, dB = 10, 0.03
                    ratio = (lam - lam0) / lam0
                    p = A * ratio * (1.0 + B * ratio)
                    dp = (
                        (ratio * (1 + B * ratio) * dA)**2
                        + (A * ratio**2 * dB)**2
                        + (A * (1 + 2 * B * ratio) / lam0 * lam_err)**2
                    )**0.5
            
                    return p, dp

            # --- Sm2+:SrB4O7 ---
            if sensor == "sm_srb4o7":
                def datchi_borate_calc(C, a, b, dlam, C_err, a_err, b_err):
                    p = C * dlam * (1 + a * dlam) / (1 + b * dlam)

                    dp_dC = dlam * (1 + a*dlam) / (1 + b*dlam)

                    dp_da = C * dlam**2 / (1 + b*dlam)

                    dp_db = - C * dlam**2 * (1 + a*dlam) / (1 + b*dlam)**2

                    dp_dlam = C * (
                        (1 + 2*a*dlam)/(1 + b*dlam)
                        - (b*dlam*(1 + a*dlam))/(1 + b*dlam)**2
                    )

                    dp = np.sqrt(
                        (dp_dC * C_err)**2 +
                        (dp_da * a_err)**2 +
                        (dp_db * b_err)**2 +
                        (dp_dlam * lam_err)**2
                    )

                    return p, dp
                
                # def rashchenko_borate_calc(
                #     lam, lam0, lam_err,
                #     a, b, a_err, b_err
                # ):
                #     dlam = lam - lam0

                #     D = b**2 + 4*a*dlam
                #     sqrtD = np.sqrt(D)

                #     p = (-b + sqrtD) / (2*a)

                #     dp_ddlam = 1 / sqrtD
                #     dp_db = (-1 + b / sqrtD) / (2*a)
                #     dp_da = dlam / (a * sqrtD) - (-b + sqrtD) / (2 * a**2)

                #     p_err = np.sqrt(
                #         (dp_ddlam * lam_err)**2 +
                #         (dp_da * a_err)**2 +
                #         (dp_db * b_err)**2
                #     )

                #     return p, p_err

                if p_scale == "sm_srb4o7_datchi_1997_mxb1986":
                    return datchi_borate_calc(4.032, 9.29e-3, 2.32e-2, lam - lam0, 0, 0, 0)
                elif p_scale == "sm_srb4o7_datchi_2007_do2007":
                    return datchi_borate_calc(3.989, 0.006915, 0.0166, lam-lam0, 0.006, 0.000074, 0.001)
                elif p_scale == "sm_srb4o7_rashchenko_2018_lam1":
                    # A = 2836(21), B = 14.3(9)
                    return calc_mao_type(lam, lam0, lam_err, 2836, 14.3, 21, 0.9)
                elif p_scale == "sm_srb4o7_rashchenko_2018_lam2":
                    # A =3259(20), B= -19.6(12)
                    return calc_mao_type(lam, lam0, lam_err, 3259, -19.6, 20, 1.2)
                elif p_scale == "sm_srb4o7_rashchenko_2018_lam3":
                    # A =2389(15), B = -0.9(7)
                    return calc_mao_type(lam, lam0, lam_err, 2389, -0.9, 15, 0.7)   
                elif p_scale == "sm_srb4o7_rashchenko_2018_lam4":
                    # A = 2988(36), B = 35.7(15)
                    return calc_mao_type(lam, lam0, lam_err, 2988, 35.7, 36, 1.5)

            # Raman sensors
            # 表記が気持ち悪いため・・・
            nu = lam
            nu0 = lam0
            nu0_at_t0 = lam0_at_t0
            nu_err = lam_err

            
            if sensor == "diamond_13c_1st_order":
                if p_scale == "diamond_13c_schiferl_1997":
                    return (nu - nu0) / 2.83, (nu_err) / 2.83
                elif p_scale == "diamond_13c_mysen_yamashita_2010":
                    a = 1.65e-2
                    a_err = 0.044e-2      # = 4.4e-4

                    b = 1.769e-5
                    b_err = 0.0046e-5     # = 4.6e-8

                    c = 0.002707 * 1000

                    p = ((nu - nu0) + a * current_t + b * current_t**2) / c 

                    p_err = np.sqrt(
                        nu_err**2 +
                        (current_t * a_err)**2 +
                        (current_t**2 * b_err)**2
                    ) / c

                    return p, p_err
                                        
                
            if sensor == "cubic_bn_to": 
                if p_scale == "cubic_bn_datchi_2004":
                    a = -9.3*10**-3
                    b = -1.54*10**-5
                    c0 = 3.07
                    c1 = 1.25*10**-3
                    c2=-1.03*10**-6
                    d = -0.0103
                    A  = c0 + c1 * current_t + c2 * current_t**2
                    B = nu0_at_t0 + a*current_t + b*current_t**2
                    p = -1/(2*d) * (A + np.sqrt(A**2 + 4*d*(nu - B)))

                    X = A**2 + 4*d*(nu - B)
                    dp = nu_err / np.sqrt(X)
                    return p, dp
                if p_scale == "cubic_bn_kawamoto_2004":
                    a = 3.45
                    a_err = 0.03
                    p = (nu - nu0) / a
                    dp = np.sqrt((nu_err / a)**2 + ((nu - nu0) / a**2 * a_err)**2)
                    return p, dp
                
            if sensor == "zircon_b1g":
                if p_scale == "zircon_schmidt_2013":
                    return (nu-nu0)/5.69, nu_err / 5.69

                elif p_scale == "zircon_takahashi_2024":
                    return (nu-nu0)/5.48, nu_err / 5.48
                

            return None, None
        except ZeroDivisionError as e:
            print(f"ZeroDivisionError in pressure calculation ({sensor}, {p_scale}): {e}")
            return None, None
        except ValueError as e:
            print(f"ValueError in pressure calculation ({sensor}, {p_scale}): {e}")
            return None, None
        except KeyError as e:
            print(f"KeyError in pressure calculation - missing parameter: {e}")
            return None, None
        except Exception as e:
            print(f"Unexpected error in pressure calculation ({sensor}, {p_scale}): {e}")
            return None, None

    @staticmethod
    def get_corrected_lam0(*, sensor: str, t_scale: str, current_t: float, t0: float,
                            lam0_at_t0: float) -> float:
        """温度補正されたゼロ圧力ピーク位置を計算

        全引数キーワード専用・すべて必須。

        Args:
            sensor: センサー名
            t_scale: 温度スケール
            current_t: 現在の温度
            t0: 基準温度
            lam0_at_t0: 基準温度でのゼロ圧力ピーク位置

        Returns:
            補正されたゼロ圧力ピーク位置
        """
        if sensor == "ruby":

            def calculate_debye_model(alpha, theta, temperature):
                def integrand(x):
                    if x > 700:  # Avoid overflow for large x
                        return 0
                    else:
                        return x ** 3 / (np.exp(x) - 1)
                
                if temperature == 0:
                    integral = 0
                else:
                    integral, _ = quad(integrand, 0, theta / temperature)
                return alpha * (temperature / theta)**4 * integral  
            
            def datchi_ruby_temp(temp, a1, a2, a3):
                    # Note: this function returns the absolute wavelength reported in the literature, not the shift from the input lam0_at_t0.
                    if temp < 50:
                        return -0.887
                    else:
                        wl_at_296K = 694.281
                        deltat = temp - 296
                        return wl_at_296K + a1 * deltat + a2 * deltat**2 + a3 * deltat ** 3

            if t_scale == "ruby_ragan_1992":
                def ragan_ruby_temp(temp):
                    wn = 14423 + 4.49 * 10 **-2 * temp -4.81 * 10**-4 * temp ** 2 +3.71 * 10**-7 * temp ** 3
                    return 10 ** 7 / wn
                offset = ragan_ruby_temp(t0) - lam0_at_t0
                return ragan_ruby_temp(current_t) - offset
            
            elif t_scale == "ruby_datchi_2007_ht":
                a1, a2, a3 = 0.00746, -3.01e-6, 8.76e-9
                offset = datchi_ruby_temp(t0, a1, a2, a3) - lam0_at_t0
                return datchi_ruby_temp(current_t, a1, a2, a3) - offset
            
            elif t_scale == "ruby_datchi_2007_lt":
                a1, a2, a3 = 0.00664, 6.76e-6, -2.33e-8
                offset = datchi_ruby_temp(t0, a1, a2, a3) - lam0_at_t0
                return datchi_ruby_temp(current_t, a1, a2, a3) - offset

            elif t_scale == "ruby_kobayashi_unpublished":
                wn_at_t0 = 10 ** 7 / lam0_at_t0
                alpha = -458.9
                theta = 794.0
                wn_at_current_t = wn_at_t0 + calculate_debye_model(alpha, theta, current_t) - calculate_debye_model(alpha, theta, t0)
                return 10 ** 7 / wn_at_current_t
            
            elif t_scale == "ruby_yen_nicol_1992":
                wn_at_t0 = 10 ** 7 / lam0_at_t0
                alpha = -419
                theta = 760
                wn_at_current_t = wn_at_t0 + calculate_debye_model(alpha, theta, current_t) - calculate_debye_model(alpha, theta, t0)
                return 10 ** 7 / wn_at_current_t
            

        if sensor == "sm_srb4o7": 
            if t_scale == "sm_srb4o7_datchi_2007":
                def datchi_borate_temp(temp):
                    deltat = temp - 296
                    return -8.7 * 10**-5 * deltat + 4.62 * 10**-6 * deltat**2 -2.38 * 10**-9 * deltat**3  
                offset = datchi_borate_temp(t0) - lam0_at_t0
                return datchi_borate_temp(current_t) - offset
            
        if sensor == "zircon_b1g":
            if t_scale == "zircon_schmidt_2013":
                def schmidt_zircon_temp(temp): # in degC !!
                    return 7.53 * 10**-9 * temp**3 - 1.61 * 10**-5 * temp**2 - 2.89 * 10**-2 * temp + 1008.9
                calc_nu_at_t0 = schmidt_zircon_temp(t0-273.15)
                offset = calc_nu_at_t0 - lam0_at_t0
                return schmidt_zircon_temp(current_t-273.15) - offset
            
            if t_scale == "zircon_takahashi_2024":
                def takahashi_zircon_temp(temp): # in K
                    return 7.54 * 10**-9 * temp**3 - 2.23 * 10**-5 * temp**2 - 1.84 * 10**-2 * temp + 1015.44
                calc_nu_at_t0 = takahashi_zircon_temp(t0)
                offset = calc_nu_at_t0 - lam0_at_t0
                return takahashi_zircon_temp(current_t) - offset
        if sensor == "cubic_bn_to":
            if t_scale == "cubic_bn_kawamoto_2004":
                def kawamoto_BN_temp(temp):
                    a0 = 1060.6
                    a1 = -0.010
                    a2 = -1.42 * 10**-5
                    return a0 + a1*temp + a2*temp**2
                calc_nu_at_t0 = kawamoto_BN_temp(t0)
                offset = calc_nu_at_t0 - lam0_at_t0
                return kawamoto_BN_temp(current_t) - offset
        return lam0_at_t0
