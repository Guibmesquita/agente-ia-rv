# Relatório de Diagnóstico: Migração pdf2image → PyMuPDF

**Data:** 2026-02-24  
**Autor:** Agente IA (Stevan)  
**Severidade:** Crítica (bloqueava upload de materiais em produção)  
**Status:** Resolvido

---

## 1. Problema Identificado

### Sintoma
Ao fazer upload de PDFs pela interface administrativa em produção (`agente-ia-rv-svn.replit.app`), o processamento falhava com o seguinte erro:

```
Unable to get page count. Is poppler installed and in PATH?
```

### Causa Raiz
A biblioteca `pdf2image` (Python) é apenas um wrapper que invoca o binário de sistema `pdftoppm` (parte do pacote `poppler-utils`). No ambiente de desenvolvimento local (NixOS/Replit), o `poppler_utils` estava instalado como dependência de sistema. Porém, no ambiente de produção (Cloud Run), esse binário **não está disponível** porque:

1. O deploy do Replit empacota apenas o código Python e suas dependências pip.
2. Dependências de sistema (binários nativos) não são incluídas automaticamente no container de produção.
3. O `poppler-utils` é um pacote de sistema operacional (apt/nix), não um pacote Python.

### Impacto
- **Upload de materiais:** 100% bloqueado em produção. Nenhum PDF podia ser processado.
- **Extração via GPT-4 Vision:** Impossível converter páginas em imagens para análise.
- **Base de conhecimento:** Não recebia novos conteúdos em produção.
- **Derivativos XPI:** Scripts de ingestão também afetados.

---

## 2. Solução Implementada

### Decisão Técnica
Substituir `pdf2image` por `PyMuPDF` (pacote pip: `PyMuPDF`, importado como `fitz`).

### Justificativa
| Critério | pdf2image | PyMuPDF (fitz) |
|---|---|---|
| Dependência de sistema | Requer `poppler-utils` (binário) | Nenhuma (puro Python/C compilado) |
| Instalação | `pip install pdf2image` + sistema | `pip install PyMuPDF` |
| Compatibilidade Cloud Run | Falha | Funciona |
| Performance | Boa | Excelente (mais rápida) |
| Funcionalidades | Apenas conversão | Conversão + extração de texto + manipulação |

### Arquivos Modificados
1. **`services/document_processor.py`** — Métodos `_pdf_to_images()`, `_pdf_page_to_image()`, `get_pdf_page_count()`
2. **`services/upload_queue.py`** — Processamento assíncrono de PDFs na fila
3. **`api/endpoints/products.py`** — Endpoint de upload de materiais
4. **`scripts/xpi_derivatives/ingest_derivatives.py`** — Extração de diagramas e processamento Vision
5. **`scripts/xpi_derivatives/process_pdfs_complete.py`** — Processamento em lote de PDFs

### Padrão de Código Aplicado
Antes (pdf2image):
```python
from pdf2image import convert_from_path
images = convert_from_path(pdf_path, dpi=150)
```

Depois (PyMuPDF):
```python
import fitz
from PIL import Image

doc = fitz.open(pdf_path)
zoom = 150 / 72.0
matrix = fitz.Matrix(zoom, zoom)
images = []
for page in doc:
    pix = page.get_pixmap(matrix=matrix)
    images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
doc.close()
```

O fator de zoom é calculado como `dpi_desejado / 72.0` porque o PyMuPDF usa 72 DPI como base.

---

## 3. Validação

### Teste Local
```
Testing with: Booster_1770399808256.pdf
Page count: 5
Images generated: 5
First image size: (1240, 1755)
Single page image: (1240, 1755)
```

### Checklist
- [x] Zero referências a `pdf2image` ou `convert_from_path` no código
- [x] `PyMuPDF` presente no `pyproject.toml` / dependências
- [x] Aplicação inicia sem erros
- [x] Processamento de PDF funciona localmente
- [x] Nenhuma dependência de binários de sistema para PDFs

---

## 4. Recomendações

1. **Re-publicar a aplicação** para que a correção entre em vigor em produção.
2. **Testar upload de um PDF** em produção após o deploy para confirmar.
3. **Monitorar logs** nas primeiras horas para garantir estabilidade.
4. **Remover `pdf2image`** do `pyproject.toml` / `requirements.txt` se ainda estiver listada (dependência morta).
