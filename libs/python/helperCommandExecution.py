from subprocess import run, PIPE
from libs.python.helperGeneric import getDictWithEnvVariables
from libs.python.helperJson import convertStringToJson, getJsonFromFile
import sys
import time
import os
import logging

log = logging.getLogger(__name__)


def runShellCommand(btpUsecase, command, format, info):
    return runShellCommandFlex(btpUsecase, command, format, info, True, False)


def login_cf(btpUsecase):
    cfDefined = checkIfCfEnvironmentIsDefined(btpUsecase)
    if cfDefined is True:
        accountMetadata = btpUsecase.accountMetadata

        # TBD: check, if we should switch from accountMetadata["org"] to btpUsecase.org
        org = accountMetadata["org"]

        myemail = btpUsecase.myemail
        password = btpUsecase.mypassword

        cfApiEndpoint = accountMetadata["cfapiendpoint"]

        message = (
            "Logging-in to your CF environment in the org >"
            + org
            + "< for your user >"
            + myemail
            + "<",
        )

        command = None
        pipe = False
        if btpUsecase.loginmethod == "sso":
            # Interactive login with SSO
            # Limitation: If more than one CF space exists, the execution will fail due to interactive data entry
            # error message is: "inappropriate ioctl for device"
            # This is an issue with the CF API and not with the script
            command = "cf login -a '" + cfApiEndpoint + "' -o '" + org + "' --sso"
            pipe = True

            runShellCommandFlex(
                btpUsecase,
                command,
                "INFO",
                message,
                True,
                pipe,
            )

        else:
            password = escapePassword(password)
            # NON-Interactive login with user and password
            # To avoid failure due to interaction in case of multiple spaces, we use the manual authentication flow
            # Step 1 - set api endpoint
            command = "cf api " + cfApiEndpoint
            message = (
                "Non-interactive login step 1: set CF API endpoint to >"
                + cfApiEndpoint
                + "<"
            )
            runShellCommandFlex(btpUsecase, command, "INFO", message, True, pipe)

            # Step 2 - login
            command = "cf auth " + myemail + " " + password
            message = (
                "Non-interactive login step 2: authenticate to CF with user >"
                + myemail
                + "<"
            )
            runShellCommandFlex(btpUsecase, command, "INFO", message, True, pipe)

            # Step 3 - set org
            command = "cf target -o " + org
            message = "Non-interactive login step 3: set CF org to >" + org + "<"
            runShellCommandFlex(btpUsecase, command, "INFO", message, True, pipe)


def login_btp(btpUsecase):
    myemail = btpUsecase.myemail
    password = btpUsecase.mypassword
    globalaccount = btpUsecase.globalaccount
    btpCliRegion = btpUsecase.btpcliapihostregion

    command = (
        "btp login --url 'https://cpcli.cf."
        + btpCliRegion
        + ".hana.ondemand.com' --subdomain '"
        + globalaccount
        + "'"
    )
    if btpUsecase.loginmethod == "sso":
        message = (
            "Logging-in to your global account with subdomain ID >"
            + globalaccount
            + "<"
        )
        command = command + " --sso"
        runShellCommandFlex(btpUsecase, command, "INFO", message, True, True)
        fetchEmailAddressFromBtpConfigFile(btpUsecase)
    else:
        password = escapePassword(password)

        message = (
            "Logging-in to your global account with subdomain ID >"
            + str(globalaccount)
            + "< for your user >"
            + str(myemail)
            + "<"
        )
        command = (
            command
            + " --user '"
            + str(myemail)
            + "' --password '"
            + str(password)
            + "'"
        )
        runShellCommandFlex(btpUsecase, command, "INFO", message, True, False)


def fetchEmailAddressFromBtpConfigFile(btpUsecase):
    btpConfigFile = os.environ["BTP_CLIENTCONFIG"]
    jsonResult = getJsonFromFile(
        filename=btpConfigFile,
        externalConfigAuthMethod=btpUsecase.externalConfigAuthMethod,
        externalConfigUserName=btpUsecase.externalConfigUserName,
        externalConfigPassword=btpUsecase.externalConfigPassword,
        externalConfigToken=btpUsecase.externalConfigToken,
    )
    if "Authentication" in jsonResult and "Mail" in jsonResult["Authentication"]:
        btpUsecase.myemail = jsonResult["Authentication"]["Mail"]
        return btpUsecase.myemail
    return None


def runShellCommandFlex(btpUsecase, command, format, info, exitIfError, noPipe):
    if info is not None:
        if format == "INFO":
            log.info(info)
        if format == "CHECK":
            log.check(info)
        if format == "WARN":
            log.warning(info)

    # Check whether we are calling a btp or cf command
    # If yes, we should initiate first a re-login, if necessary
    checkIfReLoginNecessary(btpUsecase, command)

    foundPassword = False
    if btpUsecase.logcommands is True:
        # Avoid to show any passwords in the log
        passwordStrings = ["password ", " -p ", " --p "]
        for passwordString in passwordStrings:
            if passwordString in command:
                commandToBeLogged = (
                    command[0 : command.index(passwordString) + len(passwordString) + 1]
                    + "xxxxxxxxxxxxxxxxx"
                )
                log.command(commandToBeLogged)
                foundPassword = True
                break
        if "cf auth" in command:
            log.command("cf auth xxxxxxxxxxxxxxxxx")
            foundPassword = True
        if foundPassword is False:
            log.command(command)
    p = None
    if noPipe is True:
        p = run(command, shell=True, env=getDictWithEnvVariables(btpUsecase))
    else:
        p = run(
            command,
            shell=True,
            stdout=PIPE,
            stderr=PIPE,
            env=getDictWithEnvVariables(btpUsecase),
        )
        output = p.stdout.decode()
        error = p.stderr.decode()
    returnCode = p.returncode

    if returnCode == 0 or exitIfError is False:
        return p
    else:
        if p is not None and p.stdout is not None:
            output = p.stdout.decode()
            error = p.stderr.decode()
            log.error(output)
            log.error(error)
        else:
            log.error(
                "Something went wrong, but the script can not fetch the error message. Please check the log messages before."
            )
        sys.exit(returnCode)


def checkIfReLoginNecessary(btpUsecase, command):
    # time in seconds for re-login
    ELAPSEDTIMEFORRELOGIN = 45 * 60

    reLogin = False
    elapsedTime = 0
    currentTime = time.time()

    if command[0:9] == "btp login":
        btpUsecase.timeLastCliLogin = currentTime
        return None

    if command[0:8] == "cf login":
        btpUsecase.timeLastCliLogin = currentTime
        return None

    if btpUsecase.timeLastCliLogin is None:
        btpUsecase.timeLastCliLogin = currentTime

    elapsedTime = currentTime - btpUsecase.timeLastCliLogin

    if elapsedTime > ELAPSEDTIMEFORRELOGIN:
        reLogin = True
    else:
        reLogin = False

    if command[0:4] == "btp " and command[0:9] != "btp login" and reLogin is True:
        minutesPassed = "{:.2f}".format(elapsedTime / 60)
        log.warning(
            "executing a re-login in SAP btp CLI and CF CLI as the last login happened more than >"
            + minutesPassed
            + "< minutes ago"
        )
        login_btp(btpUsecase)
        cfDefined = checkIfCfEnvironmentIsDefined(btpUsecase)
        if cfDefined is True:
            login_cf(btpUsecase)
        btpUsecase.timeLastCliLogin = currentTime

    if command[0:3] == "cf " and command[0:8] != "cf login" and reLogin is True:
        minutesPassed = "{:.2f}".format(elapsedTime / 60)
        log.warning(
            "executing a re-login in SAP btp CLI and CF CLI as the last login happened more than >"
            + minutesPassed
            + "< minutes ago"
        )
        login_btp(btpUsecase)
        cfDefined = checkIfCfEnvironmentIsDefined(btpUsecase)
        if cfDefined is True:
            login_cf(btpUsecase)
        btpUsecase.timeLastCliLogin = currentTime


def checkIfCfEnvironmentIsDefined(btpUsecase):
    for environment in btpUsecase.definedEnvironments:
        if environment.name == "cloudfoundry":
            return True
    return False


def runCommandFlexAndGetJsonResult(
    btpUsecase, command, format, message, exitIfError: bool = True
):
    p = runShellCommandFlex(btpUsecase, command, format, message, exitIfError, False)
    list = p.stdout.decode()
    list = convertStringToJson(list)
    return list


def runCommandAndGetJsonResult(btpUsecase, command, format, message):
    p = runShellCommand(btpUsecase, command, format, message)
    list = p.stdout.decode()
    list = convertStringToJson(list)
    return list


def executeCommandsFromUsecaseFile(btpUsecase, message, jsonSection):
    usecaseDefinition = getJsonFromFile(
        filename=btpUsecase.usecasefile,
        externalConfigAuthMethod=btpUsecase.externalConfigAuthMethod,
        externalConfigUserName=btpUsecase.externalConfigUserName,
        externalConfigPassword=btpUsecase.externalConfigPassword,
        externalConfigToken=btpUsecase.externalConfigToken,
    )

    if jsonSection in usecaseDefinition and len(usecaseDefinition[jsonSection]) > 0:
        commands = usecaseDefinition[jsonSection]
        log.header(message)

        for command in commands:
            if "description" in command and "command" in command:
                message = command["description"]
                thisCommand = command["command"]
                log.header("COMMAND EXECUTION: " + message)

                p = runShellCommandFlex(
                    btpUsecase,
                    thisCommand,
                    "INFO",
                    "Executing the following commands:\n" + thisCommand + "\n",
                    True,
                    True,
                )
                if p is not None and p.stdout is not None:
                    result = p.stdout.decode()
                    log.success(result)


def escapePassword(password) -> str:
    if '"' in password or "'" in password:
        log.info("escaping special characters in password")
        password = password.replace('"', '"')
        password = password.replace("'", "'")

    return password
