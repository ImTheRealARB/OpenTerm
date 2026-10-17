import { Board } from "./Board";
import { FX as DEF } from "./boards";
import type { FunctionProps } from "./registry";

export default function FX(props: FunctionProps) {
  return <Board {...props} def={DEF} />;
}
