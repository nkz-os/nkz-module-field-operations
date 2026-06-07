import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';

interface PhotoUploadProps {
  operationId: string;
  currentUrl?: string;
  onUploaded?: (url: string) => void;
}

const MAX_SIZE_BYTES = 10 * 1024 * 1024; // 10 MB
const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/heic', 'image/heif'];

const PhotoUpload: React.FC<PhotoUploadProps> = ({ operationId, currentUrl, onUploaded }) => {
  const { t } = useTranslation('field-operations');
  const [preview, setPreview]     = useState<string | null>(currentUrl ?? null);
  const [uploading, setUploading] = useState(false);
  const [error, setError]         = useState<string | null>(null);

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > MAX_SIZE_BYTES) {
      setError(t('photo.fileTooLarge'));
      return;
    }
    if (!ACCEPTED_TYPES.includes(file.type)) {
      setError(t('photo.invalidType'));
      return;
    }

    setError(null);
    setUploading(true);

    // Show local preview immediately
    const reader = new FileReader();
    reader.onload = ev => setPreview(ev.target?.result as string);
    reader.readAsDataURL(file);

    try {
      const formData = new FormData();
      formData.append('label_photo', file);
      formData.append('operation_id', operationId);

      const resp = await fetch(
        `/api/field-operations/operations/${encodeURIComponent(operationId)}/label-photo`,
        { method: 'POST', body: formData, credentials: 'include' }
      );
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (data.url) {
        setPreview(data.url);
        onUploaded?.(data.url);
      }
    } catch (err) {
      setError(t('photo.uploadError'));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="mt-4" id={`photo-upload-${operationId.split(':').pop()}`}>
      <label className="block text-xs font-semibold text-nkz-text-muted mb-1 uppercase tracking-wide">
        {t('photo.label')}
      </label>

      {preview ? (
        <div className="flex items-center gap-3">
          <img
            src={preview}
            alt={t('photo.label')}
            className="w-16 h-16 object-cover rounded-lg border border-nkz-border shadow-sm"
          />
          <div>
            <p className="text-xs text-nkz-text-muted">{t('photo.uploaded')}</p>
            <label className="mt-1 text-xs text-nkz-accent-base hover:underline cursor-pointer">
              {t('photo.change')}
              <input
                type="file"
                accept="image/jpeg,image/png,.heic,.heif"
                onChange={handleFileChange}
                className="hidden"
              />
            </label>
          </div>
        </div>
      ) : (
        <label
          className={`
            flex flex-col items-center justify-center gap-1 w-full h-20
            border-2 border-dashed border-nkz-border rounded-lg cursor-pointer
            hover:border-nkz-accent-base hover:bg-nkz-surface transition-colors
            ${uploading ? 'opacity-50 cursor-wait' : ''}
          `}
        >
          <span className="text-xl">{uploading ? '⏳' : '📷'}</span>
          <span className="text-xs text-nkz-text-muted">
            {uploading ? t('photo.uploading') : t('photo.dropOrClick')}
          </span>
          <span className="text-[10px] text-nkz-text-muted">JPG · PNG · HEIC · máx 10 MB</span>
          <input
            type="file"
            accept="image/jpeg,image/png,.heic,.heif"
            onChange={handleFileChange}
            disabled={uploading}
            className="hidden"
          />
        </label>
      )}

      {error && (
        <p className="mt-1 text-xs text-red-500">{error}</p>
      )}
    </div>
  );
};

export default PhotoUpload;
