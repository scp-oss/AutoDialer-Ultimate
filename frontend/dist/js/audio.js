/* Audio Module - Стили для AutoDialer Ultimate */

/* Библиотека */
.library-container {
  padding: 20px 0;
}

.library-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 10px;
}

.search-box {
  flex: 1;
  min-width: 250px;
}

.toolbar-actions {
  display: flex;
  gap: 10px;
}

.file-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.file-icon {
  font-size: 1.5rem;
}

.file-details {
  display: flex;
  flex-direction: column;
}

.file-details small {
  color: #6c757d;
  font-size: 0.85rem;
}

.badge-tts {
  background: #28a745;
  color: white;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.75rem;
}

.badge-upload {
  background: #007bff;
  color: white;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.75rem;
}

.audio-table-container {
  overflow-x: auto;
}

#audio-table tbody tr.selected {
  background: #e7f3ff;
}

.empty-state {
  text-align: center;
  padding: 40px;
}

.empty-icon {
  font-size: 4rem;
  margin-bottom: 20px;
}

/* TTS */
.tts-container {
  padding: 20px 0;
}

.row {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}

.col-md-7 {
  flex: 7;
  min-width: 300px;
}

.col-md-5 {
  flex: 5;
  min-width: 250px;
}

.tts-form-panel,
.tts-history-panel {
  background: #f8f9fa;
  padding: 20px;
  border-radius: 8px;
  height: 100%;
}

.tts-form-panel h3,
.tts-history-panel h3 {
  margin-top: 0;
  margin-bottom: 15px;
}

.history-item {
  background: white;
  padding: 10px;
  border-radius: 5px;
  margin-bottom: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.history-info {
  flex: 1;
}

.history-text {
  color: #6c757d;
  font-size: 0.85rem;
  margin: 5px 0 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.history-actions {
  display: flex;
  gap: 5px;
}

.form-actions {
  margin-top: 20px;
}

/* Загрузка */
.upload-container {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px 0;
}

.upload-area {
  border: 3px dashed #dee2e6;
  border-radius: 10px;
  padding: 50px;
  text-align: center;
  background: #f8f9fa;
  transition: all 0.3s;
  cursor: pointer;
}

.upload-area.drag-over {
  border-color: #007bff;
  background: #e7f3ff;
}

.upload-icon {
  font-size: 4rem;
  margin-bottom: 20px;
}

.upload-hint {
  margin-top: 20px;
  color: #6c757d;
  font-size: 0.9rem;
}

#upload-queue {
  margin-top: 30px;
  padding: 20px;
  background: #f8f9fa;
  border-radius: 8px;
}

.queue-item {
  background: white;
  padding: 15px;
  border-radius: 5px;
  margin-bottom: 10px;
}

.queue-item-info {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.queue-progress {
  height: 10px;
  background: #e9ecef;
  border-radius: 5px;
  overflow: hidden;
  margin-bottom: 5px;
}

.progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #007bff, #00a8ff);
  transition: width 0.3s;
  width: 0%;
}

.queue-status {
  font-size: 0.9rem;
  color: #6c757d;
}

.queue-item.uploaded .queue-status {
  color: #28a745;
}

.queue-item.error .queue-status {
  color: #dc3545;
}

/* Модальное окно TTS результата */
.tts-result {
  max-width: 600px;
}

.audio-player-container {
  margin: 20px 0;
}

.preview-content {
  max-height: 150px;
  overflow-y: auto;
  padding: 10px;
  background: #f8f9fa;
  border-radius: 5px;
  font-size: 0.9rem;
  white-space: pre-wrap;
}

.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

/* Пагинация */
.pagination-container {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 20px;
  padding: 10px 0;
}

.pagination-info {
  color: #6c757d;
}

.pagination-controls {
  display: flex;
  gap: 10px;
}

/* Вкладки */
.tabs-container {
  margin-bottom: 20px;
  border-bottom: 2px solid #dee2e6;
}

.tabs {
  display: flex;
  gap: 5px;
}

.tab {
  padding: 10px 20px;
  background: none;
  border: none;
  border-bottom: 3px solid transparent;
  cursor: pointer;
  font-size: 1rem;
  color: #6c757d;
  transition: all 0.3s;
}

.tab:hover {
  color: #495057;
  background: #f8f9fa;
}

.tab.active {
  color: #007bff;
  border-bottom-color: #007bff;
}

.tab-content {
  padding: 20px 0;
}

/* Кнопки действий */
.action-buttons {
  display: flex;
  gap: 5px;
}

.btn-success {
  background: #28a745;
  color: white;
  border: none;
}

.btn-success:hover {
  background: #218838;
}

.btn-danger {
  background: #dc3545;
  color: white;
  border: none;
}

.btn-danger:hover {
  background: #c82333;
}

.text-error {
  color: #dc3545;
}

.text-center {
  text-align: center;
}

.text-muted {
  color: #6c757d;
}
