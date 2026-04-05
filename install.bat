@echo off
echo =========================================
echo   AutoTrader IA - Instalacion
echo =========================================
echo.
echo Creando entorno virtual...
python -m venv venv
call venv\Scripts\activate

echo.
echo Instalando dependencias...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Copiando .env de ejemplo...
if not exist .env (
    copy .env.example .env
    echo .env creado. Edita el archivo si quieres agregar claves API.
) else (
    echo .env ya existe, no se sobreescribe.
)

echo.
echo =========================================
echo   Instalacion completada!
echo =========================================
echo.
echo Para iniciar el bot:
echo   venv\Scripts\activate
echo   python main.py
echo.
echo Para ver solo el reporte:
echo   python main.py --report
echo.
pause
