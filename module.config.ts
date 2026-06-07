import { defineModule } from '@nekazari/module-builder';

export default defineModule({
  id: 'field-operations',
  name: 'Operaciones de Campo',
  routes: [{ path: '/field-operations', component: () => import('./src/App') }],
  data: {
    entities: ['AgriParcelOperation'],
    timeseries: [],
  },
});
