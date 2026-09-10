@echo off
REM Puerta de entrada de Windows. Equivalente al Makefile, que sigue siendo la
REM referencia porque CI corre en Linux.
REM
REM   run setup
REM   run test
REM   run help
REM
REM POR QUE ESTE ARCHIVO ES UN .cmd Y NO UN .ps1
REM
REM En un Windows recien salido de fabrica la ExecutionPolicy es `Restricted` y
REM NINGUN .ps1 corre: `.\run.ps1 setup` fallaba con SecurityException antes de
REM hacer nada. Un .cmd no esta sujeto a esa politica.
REM
REM Y POR QUE run.ps1 VIVE EN scripts\ Y NO AQUI AL LADO
REM
REM Porque con los dos archivos juntos en la raiz, PowerShell resuelve `.\run` al
REM .ps1 --lo prefiere sobre el .cmd-- y el usuario volvia a comerse el mismo
REM error escribiendo el comando corto de la guia. Verificado con
REM `Get-Command .\run`, que devolvia run.ps1. Sacar el .ps1 de la raiz elimina la
REM ambiguedad en vez de documentarla.
REM
REM El bypass de abajo esta acotado a ESTA invocacion de ESTE archivo: no cambia
REM configuracion del sistema ni de la cuenta, y no persiste nada al terminar.
REM Que quede dicho sin adornos: esto rodea la ExecutionPolicy. Microsoft la
REM documenta como proteccion contra ejecucion ACCIDENTAL de scripts, no como
REM limite de seguridad, y aqui la ejecucion la pide quien escribe `run`. La
REM alternativa para quien prefiera no rodearla esta en docs/INSTALL.md.
REM
REM El pushd/popd hace que `run` funcione desde cualquier directorio: las tareas
REM asumen la raiz del repo como directorio de trabajo.

pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
