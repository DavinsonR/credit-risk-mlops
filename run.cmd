@echo off
REM Puerta de entrada de Windows. Hace lo mismo que run.ps1, y existe por una
REM razon concreta: en un Windows recien salido de fabrica, `.\run.ps1 setup`
REM NO CORRE.
REM
REM La ExecutionPolicy por defecto en Windows cliente es `Restricted`, que
REM bloquea cualquier .ps1. El primer comando de la guia de instalacion fallaba
REM con un SecurityException antes de hacer nada. No se detecto antes porque en
REM la maquina de desarrollo el scope Process estaba en Bypass: el mismo "works
REM on my machine" que ya habia mordido en CI con los extras de onnx y serve.
REM
REM Un .cmd no esta sujeto a la ExecutionPolicy, asi que este archivo funciona
REM siempre y llama a run.ps1 con el bypass acotado a ESTA invocacion:
REM
REM   - no cambia ninguna configuracion del sistema ni de la cuenta;
REM   - no queda nada persistido al terminar;
REM   - aplica solo a este archivo, no a cualquier script.
REM
REM Que quede dicho sin adornos: esto rodea la ExecutionPolicy. Microsoft la
REM documenta como una proteccion contra ejecucion ACCIDENTAL de scripts, no
REM como un limite de seguridad, y aqui la ejecucion no tiene nada de accidental
REM -- la pide quien escribio `run`. Si prefieres no rodearla, la alternativa
REM esta en docs/INSTALL.md: habilitar RemoteSigned para tu usuario, una vez.
REM
REM   run setup
REM   run test
REM   run help

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
exit /b %ERRORLEVEL%
