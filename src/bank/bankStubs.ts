import express from 'express';

export function registerBankStubs(app: express.Express) {
  app.post('/api/bank/initiate', (_req, res) => {
    res.json({ status: 'stubbed', message: 'Bank initiation API not implemented yet.' });
  });
  app.post('/api/bank/approve', (_req, res) => {
    res.json({ status: 'stubbed', message: 'Bank approve API not implemented yet.' });
  });
  app.post('/api/bank/release', (_req, res) => {
    res.json({ status: 'stubbed', message: 'Bank release API not implemented yet.' });
  });
}
