/**
 * Word lists for plain-English commands (pure data).
 *
 * FILLER: words that carry no meaning for the command. They are trimmed from both ends of the company phrase and a company
 * name never starts or ends on one (but "bank OF america" keeps its inner "of").
 *
 * COMMON_WORDS: everyday English words that are ALSO real tickers (HAS = Hasbro, ALL = Allstate, NOW = ServiceNow, IT = Gartner...).
 * Typed in lower case inside a sentence they are never read as tickers: "how has apple done" must not open Hasbro. A ticker the
 * user typed in capitals ("NOW stock") is still honoured (natural.ts passes those in).
 */
export const FILLER = new Set(
  ("show me the a an for of please open get what whats is are how doing do does did done to see give display pull up on in at and with " +
    "my us tell about look looking check can could you i want need would like let lets go find view its it s share shares " +
    "company inc corp corporation ltd plc co now currently current latest recent recently over past last this vs versus " +
    "chart charts graph graphs stock stocks price prices has have had been was were be performed perform performing performance " +
    "compare comparing comparison between against trading traded going gone since from during within through into than then so very really just also any some all").split(" "),
);

/** Lower-case words that are plain English first and tickers second. Add freely: a miss only means a word may be read as a ticker. */
export const COMMON_WORDS = new Set([
  ...FILLER,
  ...(
    "a all am an and any are as at be by can cat day did do dog eat for fun get go has he her him his how if in is it its let " +
    "low man me my new no not now nut of old on one our out put real run say see she so tax the them then they this to too " +
    "top two up us use was way we who why will win yes you your very well work year years month months week weeks time " +
    "buy sell best big cash fast free good great high just keep kind know last life like long look love make many more most much must name next " +
    "only open over own part pay plan play post pure rise safe same sell show side some such sure take tell than that their there these " +
    "think today true turn unit upon view want warm what when where which while with would about above after again ahead also among " +
    "away back been being below both bull bear call came come could does done down each ever even every find first from full gain " +
    "give goes gold gone grow half hand hard have here hold home hope hour into issue item jump just late lead less line list live " +
    "lose lost main mark mean meet mind move need none note once ones page peak pick plus pool pull push rate read rest rich risk rock " +
    "roll room rule save seem seen self send ship shop shot sign site size slow soon sort star stay step stop sure term test thus tick " +
    "tool tops trade trend trust type used user very wait walk week went were west wide wish word worth yield zero zone"
  ).split(" "),
]);
