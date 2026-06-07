type DropzoneProps = {
  file: File | null;
  onFileChange: (file: File | null) => void;
};

export function Dropzone({ file, onFileChange }: DropzoneProps) {
  return (
    <label className="dropzone">
      <input
        type="file"
        accept=".doc,.docx,.txt"
        onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
      />
      <span className="dropzone-kicker">Document Import</span>
      <span className="dropzone-title">{file ? file.name : "拖拽或点击上传剧本文件"}</span>
      <span className="dropzone-subtitle">支持 .doc / .docx / .txt，也可只填下面的纯文本内容。</span>
    </label>
  );
}
