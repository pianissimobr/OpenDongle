import { House, Globe, User, Cable, Settings, CircleHelp, Wrench, type LucideIcon } from "lucide-react"
import type { IconName } from "@/lib/panel/nav"

const MAP: Record<IconName, LucideIcon> = {
  house: House,
  globe: Globe,
  user: User,
  cable: Cable,
  settings: Settings,
  help: CircleHelp,
  wrench: Wrench,
}

export function CatIcon({ name, className }: { name: IconName; className?: string }) {
  const Cmp = MAP[name]
  return <Cmp className={className} />
}
