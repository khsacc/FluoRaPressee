Caution: This program is under active development!

[Japanese version available here](./README_ja.md)

# FluoraPressée: Andor Spectrometer Control & Analysis GUI

Author: Hiroki Kobayashi (Geochemical Research Center, The University of Tokyo). https://orcid.org/0000-0002-3682-7558 E-mail as of 2026: hiroki (at) eqchem.s.u-tokyo.ac.jp

A Python-based GUI application designed to control Andor cameras (detectors) and spectrometers. It seamlessly handles real-time spectrum acquisition, background subtraction, calibration, peak fitting, and pressure calculation for high-pressure experiments.

<!-- ## ✨ Features

* **Real-time Measurement & Control**
  * Real-time display of 1D spectra (Full Range / Custom ROI) and 2D images.
  * Control over exposure time, number of accumulations, and detector cooling temperature.
  * Supports single shots, continuous measurements, and sequential automated saving.
* **Spectrometer Control**
  * Control of grating and center wavelength.
  * Seamless switching between Wavelength (nm) and Raman shift (cm⁻¹) modes (supports excitation wavelength setting).
* **Background Correction & Calibration**
  * Acquire, save, and subtract background spectra in real-time.
  * X-axis wavelength calibration tool (supports loading previous calibration files).
* **Real-time Peak Fitting**
  * Single and double peak fitting using Gauss, Lorentz, and Pseudo-Voigt functions.
  * Automatic and manual fitting range configurations.
* **Pressure Calculation (for High-Pressure Experiments)**
  * Pressure calculation based on Ruby fluorescence shift (supports Piermarini, Mao, and Shen scales).
  * Temperature correction for the center wavelength (λ0) based on sample temperature.

## 🛠 Requirements

* **OS**: Windows 10 / 11 (Depends on Andor SDK compatibility)
* **Python**: Python 3.8 or higher
* **Hardware**:
  * Andor Camera (Detector)
  * Andor Spectrometer
* **Drivers/SDK**:
  * Andor SDK must be installed on the system.

### Dependencies
* PyQt5
* pyqtgraph
* numpy
* scipy

## 📥 Installation

1. Open Command Prompt or PowerShell.
2. Install the required Python packages:

    pip install PyQt5 pyqtgraph numpy scipy

3. Ensure the Andor SDK is properly installed.
4. Navigate to the project directory and run the script.

## 🚀 Usage

### Launching the Application
Run the application with the following command:

    python ui.py

*Note: If you want to test the UI without connecting to the hardware, you can launch it in debug mode:*

    python ui.py --debug

### Basic Measurement Workflow
1. **Cooling**: 
   Set the "Cooler target temp" in the "Measurement" panel and wait for the camera temperature to stabilize.
2. **Spectrometer Setup**: 
   In the "Spectrometer Configurations" section, enter the desired grating and center wavelength (or Raman shift), then click **"Apply"**.
3. **Background Acquisition (Optional)**: 
   Close the shutter, then click **"Acquire and save background"** in the "Background" section to collect and save background data.
4. **Measurement**:
   * **Take single spectrum**: Acquires a single spectrum based on the set exposure time and accumulations.
   * **Commence Measurement**: Continuously acquires and displays spectra in real-time. Click "Terminate Measurement" to stop.
5. **Saving Data**:
   * Click **"Save data"** to save the currently displayed spectrum.
   * For automated sequential saving, expand **"▶ Sequential measurements"**, select a directory, set the interval (Skip frames) and max number of images, then click **"Start Sequential"**.

### Fitting and Pressure Calculation
* Turn **ON** "Fitting Configurations" to perform real-time curve fitting on the displayed spectrum.
* When a double-peak fit is successful, turn **ON** the "Pressure Calculation" section to automatically calculate and display the pressure based on the Ruby R1 peak.

## 📁 File Structure

* ui.py: Main GUI application script.
* camera.py: Thread class for controlling the Andor camera, acquiring data, and reading temperature.
* spectrometer.py: Module for controlling the Andor spectrometer's gratings and wavelength.
* analysis.py: Handles peak fitting logic for spectrum data.
* calibration_ui.py: Dedicated GUI dialogue for pixel-to-wavelength calibration.
* pressureCalc.py: Module for pressure calculation logic from Ruby fluorescence.
* spectrometerConfig.json: Configuration file for gratings and ROI settings (generated automatically on first run).

# Acknowledgement

This program was developed from scratch, but many of my ideas about its design and functions come from [Rubycond](https://github.com/CelluleProjet/Rubycond) software developed by Yiuri Garino (yiuri.garino (at) cnrs.fr), which I heavily used during my stay at IMPMC, Sorbonne Universite, CNRS UMR 7590, Paris, France, where I worked with Dr Stefan Klotz.
This program was developed using spectrometers at Geochemistry laboratory lead by Prof Hiroyuki Kagi and Prof Kazuki Komatsu, at the Geochemical Research Center, Graduate School of Science, The University of Tokyo. I used Gemini Pro for coding, without which this program would never be completed. -->