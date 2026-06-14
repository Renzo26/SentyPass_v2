import { useEffect, useRef, useState } from "react";
import { Button } from "./Button";

interface Props {
  onCapture: (frames: string[]) => void;
  onCancel: () => void;
}

// Quantos frames capturar por análise (votação multi-frame) e o intervalo.
const FRAME_COUNT = 3;
const FRAME_INTERVAL_MS = 220;

export function CameraCapture({ onCapture, onCancel }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [streamReady, setStreamReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      try {
        // Pede a maior resolução possível da câmera traseira — quanto mais
        // pixels na placa, melhor a leitura do OCR.
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: "environment" },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play().catch(() => {});
        }
        setStreamReady(true);
      } catch {
        setError("Não foi possível acessar a câmera. Use o envio de arquivo abaixo.");
      }
    }
    start();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  function snapshot(): string | null {
    const video = videoRef.current;
    if (!video) return null;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth || 1920;
    canvas.height = video.videoHeight || 1080;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    // Qualidade alta (0.95) para preservar os caracteres da placa.
    return canvas.toDataURL("image/jpeg", 0.95);
  }

  async function capture() {
    if (capturing) return;
    setCapturing(true);
    // Captura uma rajada de frames — pequenas variações ajudam a votação.
    const frames: string[] = [];
    for (let i = 0; i < FRAME_COUNT; i++) {
      const shot = snapshot();
      if (shot) frames.push(shot);
      if (i < FRAME_COUNT - 1) {
        await new Promise((r) => setTimeout(r, FRAME_INTERVAL_MS));
      }
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    setCapturing(false);
    if (frames.length === 0) return;
    onCapture(frames);
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      onCapture([String(reader.result)]);
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className="fixed inset-0 z-50 bg-black flex flex-col">
      <div className="relative flex-1 flex items-center justify-center overflow-hidden">
        <video ref={videoRef} playsInline muted className="w-full h-full object-cover" />

        {/* Guia de enquadramento — ajuda a alinhar a placa e chegar perto */}
        {streamReady && !error && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <div className="w-[78%] max-w-sm aspect-[3/1] rounded-xl border-2 border-[#60a5fa]/90 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
            <p className="mt-4 px-4 text-center text-sm text-white/90 bg-black/40 rounded-full py-1.5">
              Encaixe a placa no retângulo e aproxime
            </p>
          </div>
        )}

        {!streamReady && !error && (
          <div className="absolute inset-0 flex items-center justify-center text-[#94a3b8]">
            Iniciando câmera...
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-[#f87171]">
            {error}
          </div>
        )}
      </div>
      <div className="p-4 flex flex-col gap-3 bg-[#0f172a]">
        <Button variant="primary" fullWidth onClick={capture} disabled={!streamReady || capturing}>
          {capturing ? "Capturando..." : "📸 Capturar"}
        </Button>
        <Button variant="ghost" fullWidth onClick={() => fileRef.current?.click()}>
          Enviar arquivo
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={onFileChange}
        />
        <Button variant="ghost" fullWidth onClick={onCancel}>
          Cancelar
        </Button>
      </div>
    </div>
  );
}
