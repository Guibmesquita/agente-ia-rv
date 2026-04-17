const BASE_URL = '/api';

async function fetchAPI(endpoint, options = {}) {
  const headers = {
    ...options.headers,
  };

  if (!(options.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
  }

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Sessão expirada');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Erro desconhecido' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

export const productsAPI = {
  list: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    return fetchAPI(`/products${query ? `?${query}` : ''}`);
  },

  get: (id) => fetchAPI(`/products/${id}`),

  create: (data) => fetchAPI('/products', {
    method: 'POST',
    body: JSON.stringify(data),
  }),

  update: (id, data) => fetchAPI(`/products/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  }),

  delete: (id) => fetchAPI(`/products/${id}`, {
    method: 'DELETE',
  }),

  getCategories: () => fetchAPI('/products/categories'),

  getExpiring: (days = 30) => fetchAPI(`/products/expiring?days=${days}`),

  reindex: (productId) => fetchAPI(`/products/${productId}/reindex`, { method: 'POST' }),

  toggleCommittee: (productId) => fetchAPI(`/products/${productId}/toggle-committee`, { method: 'POST' }),

  updateKeyInfo: (productId, partial) => fetchAPI(`/products/${productId}/key-info`, {
    method: 'PATCH',
    body: JSON.stringify(partial),
  }),

  linkableMaterials: (productId, q = '', limit = 40) =>
    fetchAPI(`/products/${productId}/materials-linkable?q=${encodeURIComponent(q)}&limit=${limit}`),

  linkMaterial: (productId, materialId) => fetchAPI(`/products/${productId}/link-material`, {
    method: 'POST',
    body: JSON.stringify({ material_id: materialId }),
  }),

  unlinkMaterial: (productId, materialId) => fetchAPI(`/products/${productId}/link-material/${materialId}`, {
    method: 'DELETE',
  }),

  search: (query, limit = 5) => fetchAPI(`/search/quick?q=${encodeURIComponent(query)}&limit=${limit}`),
};

export const materialsAPI = {
  get: (productId, materialId) =>
    fetchAPI(`/products/${productId}/materials/${materialId}`),

  create: (productId, data) =>
    fetchAPI(`/products/${productId}/materials`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  delete: (productId, materialId) =>
    fetchAPI(`/products/${productId}/materials/${materialId}`, {
      method: 'DELETE',
    }),

  uploadPDF: (productId, materialId, file) => {
    const formData = new FormData();
    formData.append('file', file);
    return fetchAPI(`/products/${productId}/materials/${materialId}/upload`, {
      method: 'POST',
      body: formData,
    });
  },

  reindex: (materialId) =>
    fetchAPI(`/products/materials/${materialId}/reindex`, {
      method: 'POST',
    }),


  dismissPdf: (materialId) =>
    fetchAPI(`/products/materials/${materialId}/dismiss-pdf`, {
      method: 'POST',
    }),

  updateType: (materialId, materialType) =>
    fetchAPI(`/products/materials/${materialId}/type`, {
      method: 'PATCH',
      body: JSON.stringify({ material_type: materialType }),
    }),

  uploadWithoutProduct: (file, materialData) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('material_type', materialData.material_type);
    formData.append('name', materialData.name);
    if (materialData.description) {
      formData.append('description', materialData.description);
    }
    if (materialData.valid_from) {
      formData.append('valid_from', materialData.valid_from);
    }
    if (materialData.valid_until) {
      formData.append('valid_until', materialData.valid_until);
    }
    return fetchAPI('/products/smart-upload', {
      method: 'POST',
      body: formData,
    });
  },
};

export const blocksAPI = {
  create: (productId, materialId, data) =>
    fetchAPI(`/products/${productId}/materials/${materialId}/blocks`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (productId, materialId, blockId, data) =>
    fetchAPI(`/products/${productId}/materials/${materialId}/blocks/${blockId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (productId, materialId, blockId) =>
    fetchAPI(`/products/${productId}/materials/${materialId}/blocks/${blockId}`, {
      method: 'DELETE',
    }),

  getVersions: (productId, materialId, blockId) =>
    fetchAPI(`/products/${productId}/materials/${materialId}/blocks/${blockId}/versions`),

  restoreVersion: (productId, materialId, blockId, version) =>
    fetchAPI(`/products/${productId}/materials/${materialId}/blocks/${blockId}/restore/${version}`, {
      method: 'POST',
    }),

  approve: (blockId) =>
    fetchAPI(`/products/blocks/${blockId}/approve`, {
      method: 'POST',
    }),

  bulkApprove: (blockIds) =>
    fetchAPI('/products/blocks/bulk-approve', {
      method: 'POST',
      body: JSON.stringify({ block_ids: blockIds }),
    }),
};

export const reviewAPI = {
  listPending: () => fetchAPI('/products/review/pending'),

  listPendingProducts: () => fetchAPI('/products/review/pending-products'),

  resolveProduct: (data) =>
    fetchAPI('/products/review/resolve-product', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  approve: (itemId) =>
    fetchAPI(`/products/review/${itemId}/approve`, {
      method: 'POST',
    }),

  edit: (itemId, data) =>
    fetchAPI(`/products/review/${itemId}/edit`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  reject: (itemId, data) =>
    fetchAPI(`/products/review/${itemId}/reject`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  mergeProducts: (data) =>
    fetchAPI('/products/merge-products', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

export const scriptsAPI = {
  create: (productId, data) =>
    fetchAPI(`/products/${productId}/scripts`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (productId, scriptId, data) =>
    fetchAPI(`/products/${productId}/scripts/${scriptId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  delete: (productId, scriptId) =>
    fetchAPI(`/products/${productId}/scripts/${scriptId}`, {
      method: 'DELETE',
    }),
};

export const searchAPI = {
  global: (query, limit = 20) => 
    fetchAPI(`/search/global?q=${encodeURIComponent(query)}&limit=${limit}`),
  
  quick: (query, limit = 5) =>
    fetchAPI(`/search/quick?q=${encodeURIComponent(query)}&limit=${limit}`),
};

export const adminAPI = {
  getMe: () => fetchAPI('/auth/me'),

  backfillDerivedLinks: () => fetchAPI('/products/admin/backfill-derived-links', {
    method: 'POST',
  }),

  backfillPublishAndReindex: () => fetchAPI('/products/admin/backfill-publish-and-reindex', {
    method: 'POST',
  }),

  backfillEnrichment: (onlyMissing = true, limit = 1000) =>
    fetchAPI(`/products/admin/backfill-enrichment?only_missing=${onlyMissing}&limit=${limit}`, {
      method: 'POST',
    }),

  backfillReviewQueue: () => fetchAPI('/products/admin/backfill-review-queue', {
    method: 'POST',
  }),

  listOrphans: () => fetchAPI('/products/admin/orphans'),

  archiveOrphans: (productIds) => fetchAPI('/products/admin/archive-orphans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ product_ids: productIds }),
  }),
};

export const knowledgeAPI = {
  list: () => fetchAPI('/knowledge/'),
  
  upload: (file, title, category, description) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('title', title);
    formData.append('category', category);
    if (description) formData.append('description', description);
    return fetchAPI('/knowledge/upload', {
      method: 'POST',
      body: formData,
    });
  },

  delete: (docId) =>
    fetchAPI(`/knowledge/${docId}`, {
      method: 'DELETE',
    }),
};
