import { defineModule } from '@nekazari/module-kit';
import { lazy } from 'react';
import './i18n';
import pkg from '../package.json';

const MainPage = lazy(() => import('./App'));

export default defineModule({
  id: 'field-operations',
  displayName: 'Operaciones de Campo',
  version: pkg.version,
  hostApiVersion: '^2.0.0',
  description: 'Registro de operaciones agrícolas de campo — ISOBUS + entrada manual',
  accent: { base: '#D97706', soft: '#FEF3C7', strong: '#B45309' },
  icon: 'tractor',
  main: MainPage,
  slots: {},
  data: {
    entities: ['AgriParcelOperation'],
    timeseries: [],
  },
});
