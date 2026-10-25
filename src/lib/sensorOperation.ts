// Completed irrigation operations created from water-meter readings can be corrected or revoked.
export function canCorrectSensorOperation(
  status: string, dataSource: string, operationType: string,
): boolean {
  return status === 'completed' && dataSource === 'sensor' && operationType === 'irrigation';
}
