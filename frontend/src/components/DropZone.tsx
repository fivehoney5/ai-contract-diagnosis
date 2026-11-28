import { useId, useState, type DragEvent } from 'react'
import { ACCEPT_ATTR } from '../utils/files'

interface DropZoneProps {
  label: string
  description: string
  files: File[]
  onChange: (files: File[]) => void
}

function formatSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

/** 사진·PDF를 끌어다 놓거나 골라 올리는 칸. 사진은 여러 장을 쪽 순서대로 올린다. */
export function DropZone({ label, description, files, onChange }: DropZoneProps) {
  const inputId = useId()
  const [dragging, setDragging] = useState(false)
  const hasFiles = files.length > 0

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault()
    setDragging(false)
    const dropped = Array.from(e.dataTransfer.files)
    if (dropped.length > 0) onChange(dropped)
  }

  const totalSize = files.reduce((sum, f) => sum + f.size, 0)

  return (
    <div className={`dropzone${hasFiles ? ' has-file' : ''}${dragging ? ' is-dragging' : ''}`}>
      <input
        id={inputId}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        className="visually-hidden"
        onChange={(e) => {
          onChange(Array.from(e.target.files ?? []))
          e.target.value = ''
        }}
      />
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className="dropzone__sheet" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span className="dropzone__text">
          <strong>{label}</strong>
          {hasFiles ? (
            <span className="dropzone__file">
              {files.length === 1
                ? `${files[0].name} (${formatSize(files[0].size)})`
                : `${files.length}장, 쪽 순서: ${files.map((f) => f.name).join(' → ')} (${formatSize(totalSize)})`}
            </span>
          ) : (
            <span>{description}</span>
          )}
        </span>
        <span className="dropzone__action">{hasFiles ? '다른 파일 고르기' : '파일 고르기'}</span>
      </label>
      {hasFiles && (
        <button type="button" className="btn btn--link btn--small dropzone__clear" onClick={() => onChange([])}>
          빼기
        </button>
      )}
    </div>
  )
}
