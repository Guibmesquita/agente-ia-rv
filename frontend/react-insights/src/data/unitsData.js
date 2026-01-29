export const unitsData = [
  { sigla: 'AJU', nome: 'Aracaju', x: 82, y: 42 },
  { sigla: 'CBA', nome: 'Cuiaba', x: 45, y: 52 },
  { sigla: 'CCV', nome: 'Cascavel', x: 52, y: 72 },
  { sigla: 'CGR', nome: 'Campo Grande', x: 48, y: 62 },
  { sigla: 'CTB', nome: 'Curitiba', x: 58, y: 75 },
  { sigla: 'DGT CON', nome: 'Connect', x: 52, y: 68 },
  { sigla: 'DGT CTB', nome: 'Digital Curitiba', x: 60, y: 75 },
  { sigla: 'DGT MGF', nome: 'Digital Maringa', x: 56, y: 70 },
  { sigla: 'FOZ', nome: 'Foz do Iguacu', x: 48, y: 74 },
  { sigla: 'LDB', nome: 'Londrina', x: 55, y: 69 },
  { sigla: 'MGF', nome: 'Maringa', x: 54, y: 70 },
  { sigla: 'SAO', nome: 'Sao Paulo', x: 60, y: 68 },
  { sigla: 'SSA', nome: 'Salvador', x: 80, y: 38 },
];

export const getUnitName = (sigla) => {
  const unit = unitsData.find(u => u.sigla === sigla);
  return unit ? unit.nome : sigla;
};
