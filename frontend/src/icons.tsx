import type { ReactNode } from "react";

type IconProps = { className?: string; size?: number };

function Icon({ children, size = 14, className = "" }: IconProps & { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      className={className}
    >
      {children}
    </svg>
  );
}

export function IconList(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 3h10M3 6.5h10M3 10h7M3 13h7" strokeLinecap="round" />
    </Icon>
  );
}

export function IconBarChart(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 13V8M8 13V3M13 13V9.5" strokeLinecap="round" />
    </Icon>
  );
}

export function IconMessageCircle(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2 3.5h12v7H6.5L3.5 13V10.5H2v-7Z" strokeLinejoin="round" />
    </Icon>
  );
}

export function IconCompass(props: IconProps) {
  return (
    <Icon {...props}>
      <circle cx="8" cy="8" r="5.8" />
      <path d="M10.3 5.7 8.8 9 5.7 10.3 7.2 7Z" strokeLinejoin="round" />
    </Icon>
  );
}

export function IconUpload(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 11V3M5 6l3-3 3 3M3 13h10" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  );
}

export function IconDownload(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 3v8M5 8l3 3 3-3M3 13h10" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  );
}

export function IconTransfer(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2 5.5h10M9 2.5l3 3-3 3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 10.5H4M7 13.5l-3-3 3-3" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M3 8.5l3.5 3.5L13 4.5" strokeLinecap="round" strokeLinejoin="round" />
    </Icon>
  );
}

export function IconX(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
    </Icon>
  );
}

export function IconPlus(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M8 3v10M3 8h10" strokeLinecap="round" />
    </Icon>
  );
}

export function IconSend(props: IconProps) {
  return (
    <Icon {...props}>
      <path d="M2.5 13.5 13.5 8 2.5 2.5 4.5 8 2.5 13.5Z" strokeLinejoin="round" />
    </Icon>
  );
}
