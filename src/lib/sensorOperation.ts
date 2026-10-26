// Completed irrigation operations created from water-meter readings can be corrected or revoked.
export function canCorrectSensorOperation(
  status: string, dataSource: string, operationType: string,
): boolean {
  return status === 'completed' && dataSource === 'sensor' && operationType === 'irrigation';
}

// Platform roles allowed to correct or revoke them (the backend enforces the same rule).
export const SENSOR_OPERATION_MANAGER_ROLES = ['TechnicalConsultant', 'TenantAdmin', 'PlatformAdmin'];
