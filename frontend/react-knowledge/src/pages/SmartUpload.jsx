import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { Upload, FileText, CheckCircle, ArrowRight, Sparkles, Info } from 'lucide-react';
import { materialsAPI } from '../services/api';
import { FileUpload } from '../components/FileUpload';
import { Button } from '../components/Button';
import { ProductAutocomplete } from '../components/ProductAutocomplete';
import { useToast } from '../components/Toast';

const MATERIAL_TYPES = [
  { value: 'comite', label: 'Comitê' },
  { value: 'research', label: 'Research' },
  { value: 'produto', label: 'Produto' },
  { value: 'campanha', label: 'Campanha' },
  { value: 'treinamento', label: 'Treinamento' },
  { value: 'outro', label: 'Outro' },
];

export function SmartUpload() {
  const navigate = useNavigate();
  const { addToast } = useToast();
  
  const [step, setStep] = useState(1);
  const [file, setFile] = useState(null);
  const [materialType, setMaterialType] = useState('');
  const [validFrom, setValidFrom] = useState('');
  const [validUntil, setValidUntil] = useState('');
  const [tags, setTags] = useState('');
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadComplete, setUploadComplete] = useState(false);
  const [createdMaterialId, setCreatedMaterialId] = useState(null);

  const handleUpload = async () => {
    if (!file || !materialType) {
      addToast('Selecione um arquivo e tipo de material', 'warning');
      return;
    }

    setUploading(true);
    setStep(3);

    try {
      const materialData = {
        material_type: materialType,
        name: file.name.replace('.pdf', ''),
        description: tags ? `Tags: ${tags}` : null,
        valid_from: validFrom || null,
        valid_until: validUntil || null,
      };

      let progress = 0;
      const progressInterval = setInterval(() => {
        progress += Math.random() * 15;
        if (progress > 90) progress = 90;
        setUploadProgress(Math.round(progress));
      }, 500);

      let material;
      let productId;

      if (selectedProduct) {
        productId = selectedProduct.id;
        material = await materialsAPI.create(productId, materialData);
        await materialsAPI.uploadPDF(productId, material.id, file);
      } else {
        const response = await materialsAPI.uploadWithoutProduct(file, materialData);
        material = response.material;
        productId = response.product_id;
      }

      setCreatedMaterialId(material?.id);

      clearInterval(progressInterval);
      setUploadProgress(100);
      setUploadComplete(true);
      setUploading(false);
      addToast('Documento processado com sucesso! A IA identificará automaticamente os produtos.', 'success');

    } catch (err) {
      addToast(`Erro: ${err.message}`, 'error');
      setStep(2);
      setUploading(false);
      setUploadProgress(0);
    }
  };

  const renderStep1 = () => (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6"
    >
      <div className="text-center mb-8">
        <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-4">
          <Upload className="w-8 h-8 text-primary" />
        </div>
        <h2 className="text-xl font-semibold text-foreground">Upload Inteligente</h2>
        <p className="text-muted mt-2">
          Envie um PDF e a IA extrairá automaticamente os blocos de conhecimento
        </p>
      </div>

      <FileUpload onFileSelect={setFile} />

      {file && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex justify-end"
        >
          <Button onClick={() => setStep(2)}>
            Continuar
            <ArrowRight className="w-4 h-4" />
          </Button>
        </motion.div>
      )}
    </motion.div>
  );

  const renderStep2 = () => (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
      className="space-y-6"
    >
      <div className="flex items-center gap-3 p-4 bg-primary/5 rounded-card border border-primary/20">
        <FileText className="w-6 h-6 text-primary" />
        <div className="flex-1">
          <p className="font-medium text-foreground">{file?.name}</p>
          <p className="text-sm text-muted">{(file?.size / 1024 / 1024).toFixed(2)} MB</p>
        </div>
        <button
          onClick={() => { setFile(null); setStep(1); }}
          className="text-sm text-primary hover:underline"
        >
          Trocar arquivo
        </button>
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Tipo de Material *
        </label>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {MATERIAL_TYPES.map((type) => (
            <button
              key={type.value}
              onClick={() => setMaterialType(type.value)}
              className={`px-4 py-3 rounded-card border text-sm font-medium transition-colors
                         ${materialType === type.value 
                           ? 'bg-primary text-white border-primary' 
                           : 'bg-card border-border text-foreground hover:border-primary/50'}`}
            >
              {type.label}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Produto Relacionado (opcional)
        </label>
        <ProductAutocomplete
          value={selectedProduct}
          onChange={setSelectedProduct}
          placeholder="Digite para buscar um produto..."
        />
        <div className="flex items-start gap-2 mt-2 p-3 bg-blue-50 rounded-card border border-blue-200">
          <Info className="w-4 h-4 text-blue-500 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-blue-700">
            Se não selecionar um produto, a IA identificará automaticamente os produtos mencionados em cada página do documento.
          </p>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Período de Validade (opcional)
        </label>
        <div className="grid grid-cols-2 gap-3">
          <div className="relative">
            <input
              type="date"
              value={validFrom}
              onChange={(e) => setValidFrom(e.target.value)}
              className="w-full px-4 py-3 bg-card border border-border rounded-input
                         text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            <span className="absolute -top-2 left-3 px-1 bg-card text-xs text-muted">Início</span>
          </div>
          <div className="relative">
            <input
              type="date"
              value={validUntil}
              onChange={(e) => setValidUntil(e.target.value)}
              min={validFrom || undefined}
              className="w-full px-4 py-3 bg-card border border-border rounded-input
                         text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
            <span className="absolute -top-2 left-3 px-1 bg-card text-xs text-muted">Fim</span>
          </div>
        </div>
        <p className="text-xs text-muted mt-2">
          Após a data fim, o documento não será mais consultado pelo agente
        </p>
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-2">
          Tags (opcional)
        </label>
        <input
          type="text"
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          placeholder="Ex: renda fixa, estratégia"
          className="w-full px-4 py-3 bg-card border border-border rounded-input
                     text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
        />
      </div>

      <div className="flex gap-3 pt-4">
        <Button variant="secondary" onClick={() => setStep(1)} className="flex-1">
          Voltar
        </Button>
        <Button 
          onClick={handleUpload} 
          disabled={!materialType}
          className="flex-1"
        >
          <Sparkles className="w-4 h-4" />
          Processar Automaticamente
        </Button>
      </div>
    </motion.div>
  );

  const renderStep3 = () => (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      className="text-center py-8"
    >
      {!uploadComplete ? (
        <>
          <div className="w-20 h-20 rounded-full bg-primary/10 flex items-center justify-center mx-auto mb-6">
            <Sparkles className="w-10 h-10 text-primary animate-pulse" />
          </div>
          <h2 className="text-xl font-semibold text-foreground mb-2">
            Processando documento...
          </h2>
          <p className="text-muted mb-6">
            A IA está extraindo tabelas, gráficos e textos do seu documento
          </p>
          <div className="max-w-md mx-auto">
            <div className="h-3 bg-border rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${uploadProgress}%` }}
                className="h-full bg-primary rounded-full"
              />
            </div>
            <p className="text-sm text-muted mt-2">{uploadProgress}%</p>
          </div>
        </>
      ) : (
        <>
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            className="w-20 h-20 rounded-full bg-success/10 flex items-center justify-center mx-auto mb-6"
          >
            <CheckCircle className="w-10 h-10 text-success" />
          </motion.div>
          <h2 className="text-xl font-semibold text-foreground mb-2">
            Documento processado!
          </h2>
          <p className="text-muted mb-6">
            {selectedProduct 
              ? 'Os blocos foram extraídos e estão prontos para revisão'
              : 'Os blocos foram extraídos e vinculados automaticamente aos produtos identificados'}
          </p>
          <div className="flex gap-3 justify-center">
            <Button variant="secondary" onClick={() => {
              setStep(1);
              setFile(null);
              setMaterialType('');
              setSelectedProduct(null);
              setUploadComplete(false);
              setUploadProgress(0);
              setCreatedMaterialId(null);
            }}>
              Novo Upload
            </Button>
            {selectedProduct ? (
              <Button onClick={() => navigate(`/product/${selectedProduct.id}`)}>
                Ver Produto
              </Button>
            ) : (
              <Button onClick={() => navigate('/review')}>
                Ver Fila de Revisão
              </Button>
            )}
          </div>
        </>
      )}
    </motion.div>
  );

  return (
    <div className="max-w-2xl mx-auto">
      <div className="flex items-center gap-4 mb-8">
        {[1, 2, 3].map((s) => (
          <div key={s} className="flex items-center">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium
                            ${step >= s ? 'bg-primary text-white' : 'bg-border text-muted'}`}>
              {s}
            </div>
            {s < 3 && (
              <div className={`w-16 h-0.5 ml-2 ${step > s ? 'bg-primary' : 'bg-border'}`} />
            )}
          </div>
        ))}
      </div>

      <div className="bg-card rounded-card border border-border p-8 shadow-card">
        <AnimatePresence mode="wait">
          {step === 1 && renderStep1()}
          {step === 2 && renderStep2()}
          {step === 3 && renderStep3()}
        </AnimatePresence>
      </div>
    </div>
  );
}
