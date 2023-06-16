@echo off
title Discord - Word Warden Bot
cd %~dp0
python wordwarden.py
if %errorlevel% neq 0 pause
exit