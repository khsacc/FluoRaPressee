import numpy as np
from scipy.integrate import quad

class PressureCalculator:
    # センサーごとの初期値（ゼロ圧力ピーク）
    INITIAL_VALUES = {
        "Ruby": 694.300,
        "Sm2+:SrB4O7": 685.410,
        "13C diamond 1st order": 1287.79,
        "Cubic BN TO": 1058.3,
        "Zircon B1g": 1008.6
    }

    # センサーごとに温度スケールの有効範囲を管理
    TEMP_VALID_RANGES = {
        "Ruby": {
            "Ragan et al. 1992": (0.0, 600.0),
            "Datchi et al. 1997": (296, 900) ,
            "Kobayashi et al. unpublished": (0, 300),
            "Yen and Nicol 1992": (0, 600)
        },
        "Sm2+:SrB4O7": {
            "Datchi et al. 2007": (296, 900.0)
        },
        "13C diamond 1st order": {
            "Schiferl et al. 1997": (0, 1500.0)
        },
        "Zircon B1g": {
            "Schmidt et al. 2013": (296,1223),
            "Takahashi et al. 2024": (294, 1078)
        },
        "Cubic BN TO": {
            "Datchi et al. 2004": (300, 723),
            "Kawamoto et al. 2004": (300, 1000)
        }
    }

    @staticmethod
    def is_temp_in_range(sensor, t_scale, temp):

        # 親（センサー）が存在するか
        if sensor not in PressureCalculator.TEMP_VALID_RANGES:
            return True, (None, None)
        
        # 子（温度スケール）が存在するか
        s_dict = PressureCalculator.TEMP_VALID_RANGES[sensor]
        if t_scale not in s_dict:
            return True, (None, None)
            
        rng = s_dict[t_scale]
        is_valid = rng[0] <= temp <= rng[1]
        return is_valid, rng


    @staticmethod
    def calculate(sensor, p_scale, lam, lam0, lam0_at_t0, lam_err=0.0, current_t=298.15, t0=298.15): # Raman shiftの場合、波数形式で入ってくるが、形式上lamというパラメータで統一して扱っている。波長に変換されてはいない。
        try:
            # --- Ruby Scales ---
            if sensor == "Ruby":

                if p_scale == "Piermarini et al. 1975":
                    p = 2.746 * (lam - lam0)
                    return p, 2.746 * lam_err
                
                elif p_scale == "Mao et al. 1986":
                    A, B = 1904.0, 7.665
                    dlam = lam - lam0
                    p = (A / B) * (((dlam / lam0)+1)**B - 1.0)
                    dp = (A / lam0) * (lam / lam0)**(B - 1) * lam_err
                    return p, dp
                
                elif p_scale == "Holzapfel 2003":
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
                
                elif p_scale == "Dorogokupets and Oganov 2007":
                    A=1884
                    m = 5.5
                    dlam=lam - lam0
                    p=A(dlam/ lam0) * (1+m*dlam/ lam0)

                    x = dlam / lam0
                    dp = abs(A / lam0 * (1 + 2*m*x)) * lam_err
                    return p, dp

                elif p_scale == "Shen et al. 2020":
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
            if sensor == "Sm2+:SrB4O7":
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

                if p_scale == "Datchi et al. 1997 (MXB1986)":
                    return datchi_borate_calc(4.032, 9.29e-3, 2.32e-2, lam - lam0, 0, 0, 0)
                if p_scale == "Datchi et al. 2007 (DO2007)":
                    return datchi_borate_calc(3.989, 0.006915, 0.0166, lam-lam0, 0.006, 0.000074, 0.001)

            # Raman sensors
            # 表記が気持ち悪いため・・・
            nu = lam
            nu0 = lam0
            nu0_at_t0 = lam0_at_t0
            nu_err = lam_err

            
            if sensor == "13C diamond 1st order":
                if p_scale == "Schiferl et al. 1997":
                    return (nu - nu0) / 2.83, (nu_err) / 2.83
                
            if sensor == "Cubic BN TO": 
                if p_scale == "Datchi et al. 2004":
                    a = -9.3*10**-3
                    b = -1.54*10**-5
                    c0 = 3.07
                    c1 = 1.25*10**-3
                    c2=-1.03*10**-6
                    d = -0.0103
                    A  = c0 + c1 * current_t + c2 * current_t**2
                    B = nu0_at_t0 + a*current_t + b*current_t**2
                    p = - 1/(2*d) ( A + np.sqrt(A**2 + 4*d (nu - B) ) )

                    X = A**2 + 4*d*(nu - B)
                    dp = nu_err / np.sqrt(X)
                    return p, dp
                if p_scale == "Kawamoto et al. 2004":
                    a = 3.45
                    a_err = 0.03
                    p = (nu - nu0)/a 
                    return p
                
            if sensor == "Zircon B1g": 
                if p_scale == "Schmidt et al. 2013":
                    return  (nu-nu0)/5.69, nu_err / 5.69 
                
                elif sensor == "Takahashi et al. 2024":
                    return (nu-nu0)/5.48, nu_err / 5.48 
                

            return None, None
        except:
            return None, None

    @staticmethod
    def get_corrected_lam0(sensor, t_scale, current_t, t0, lam0_at_t0):
        if sensor == "Ruby":

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

            if t_scale == "Ragan et al. 1992":
                def ragan_ruby_temp(temp):
                    wn = 14423 + 4.49 * 10 **-2 * temp -4.81 * 10**-4 * temp ** 2 +3.71 * 10**-7 * temp ** 3
                    return 10 ** 7 / wn
                offset = ragan_ruby_temp(t0) - lam0_at_t0
                return ragan_ruby_temp(current_t) - offset
            
            elif t_scale == "Datchi et al. 2007":
                def datchi_ruby_temp(temp):
                    wl_at_296K = 694.281
                    deltat = temp - 296
                    return wl_at_296K + 0.00746  * deltat -3.01* 10**-6 * deltat**2 + 8.76 * 10**-9 * deltat ** 3
                
                offset = datchi_ruby_temp(t0) - lam0_at_t0
                return datchi_ruby_temp(current_t) - offset

            elif t_scale == "Kobayashi et al. unpublished":
                wn_at_t0 = 10 ** 7 / lam0_at_t0
                alpha = -458.9
                theta = 794.0
                wn_at_current_t = wn_at_t0 + calculate_debye_model(alpha, theta, current_t) - calculate_debye_model(alpha, theta, t0)
                return 10 ** 7 / wn_at_current_t
            
            elif t_scale == "Yen and Nicol 1992":
                wn_at_t0 = 10 ** 7 / lam0_at_t0
                alpha = -419
                theta = 760
                wn_at_current_t = wn_at_t0 + calculate_debye_model(alpha, theta, current_t) - calculate_debye_model(alpha, theta, t0)
                return 10 ** 7 / wn_at_current_t
            

        if sensor == "Sm2+:SrB4O7": 
            if t_scale == "Datchi et al. 2007":
                def datchi_borate_temp(temp):
                    deltat = temp - 296
                    return -8.7 * 10**-5 * deltat + 4.62 * 10**-6 * deltat**2 -2.38 * 10**-9 * deltat**3  
                offset = datchi_borate_temp(t0) - lam0_at_t0
                return datchi_borate_temp(current_t) - offset
            
        if sensor == "Zircon B1g":
            if t_scale == "Schmidt et al. 2013":
                def schmidt_zircon_temp(temp): # in degC !!
                    return 7.53 * 10**-9 * temp**3 - 1.61 * 10**-5 * temp**2 - 2.89 * 10**-2 * temp + 1008.9
                calc_nu_at_t0 = schmidt_zircon_temp(t0-273.15)
                offset = calc_nu_at_t0 - lam0_at_t0
                return schmidt_zircon_temp(current_t-273.15) - offset
            
            if t_scale == "Takahashi et al. 2024":
                def takahashi_zircon_temp(temp): # in K
                    return 7.54 * 10**-9 * temp**3 - 2.23 * 10**-5 * temp**2 - 1.84 * 10**-2 * temp + 1015.44
                calc_nu_at_t0 = takahashi_zircon_temp(t0)
                offset = calc_nu_at_t0 - lam0_at_t0
                return takahashi_zircon_temp(current_t) - offset
        if sensor == "Cubic BN TO":
            if t_scale == "Kawamoto et al. 2004":
                def kawamoto_BN_temp(temp):
                    a0 = 1060.6
                    a1 = -0.010
                    a2 = -1.42 * 10**-5
                    return a0 + a1*temp + a2*temp**2
                calc_nu_at_t0 = kawamoto_BN_temp(t0)
                offset = calc_nu_at_t0 - lam0_at_t0
                return kawamoto_BN_temp(current_t) - offset
        return lam0_at_t0