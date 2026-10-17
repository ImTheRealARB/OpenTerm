import { createContext, useContext } from "react";

/** The id of the panel a function module is rendered in (set by Panel's FunctionView). 0 = none. */
export const PanelIdContext = createContext(0);
export const usePanelId = () => useContext(PanelIdContext);
