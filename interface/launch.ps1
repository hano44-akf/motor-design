$motorPython = 'C:/Users/jo061/AppData/Local/Python/pythoncore-3.14-64/python.exe'
Set-Location -LiteralPath $PSScriptRoot
& $motorPython (Join-Path $PSScriptRoot 'server.py')
