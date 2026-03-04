#!/bin/bash
# Adiciona os builds React ao git e commita
# Execute no Shell do Replit: bash scripts/sync-react-builds.sh

echo "=== Adicionando builds React ao git ==="
git add frontend/react-conversations/dist/
git add frontend/react-insights/dist/
git add frontend/react-costs/dist/
git add frontend/react-knowledge/dist/

echo ""
echo "=== Status dos builds no git ==="
git ls-files | grep "frontend.*dist"

echo ""
echo "=== Verificando mudanças pendentes ==="
git status --short | grep "frontend.*dist"

echo ""
echo "=== Commitando ==="
git commit -m "build: include all React builds (conversations, insights, costs, knowledge)"

echo ""
echo "=== Push para GitHub ==="
git push origin main

echo ""
echo "=== Concluído! Railway vai fazer o deploy automaticamente. ==="
