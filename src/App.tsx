import React, { useState } from 'react';
import OperationsDashboard from './components/OperationsDashboard';
import OperationDetail from './components/OperationDetail';
import type { Operation } from './components/OperationCard';

const App: React.FC = () => {
  const [selectedOp, setSelectedOp]   = useState<Operation | null>(null);
  const [refreshKey, setRefreshKey]   = useState(0);

  function handleSaved() {
    setRefreshKey(k => k + 1);
  }

  return (
    <div className="flex h-full" style={{ minHeight: 'calc(100vh - 120px)' }}>
      <div className="w-full h-full overflow-hidden">
        <OperationsDashboard
          key={refreshKey}
          onSelectOperation={op => setSelectedOp(op)}
        />
      </div>

      {selectedOp && (
        <OperationDetail
          operation={selectedOp}
          onClose={() => setSelectedOp(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  );
};

export default App;
