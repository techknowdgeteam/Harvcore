@echo off
:: Disconnects RDP but keeps the GUI console alive for AnyDesk
tscon %sessionname% /dest:console
tscon 1 /dest:console
tscon 2 /dest:console